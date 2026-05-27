#include "nix/store/filetransfer.hh"
#include "nix/store/s3-url.hh"

#include <atomic>

#include "nix/util/callback.hh"
#include "nix/util/config-global.hh"
#include "nix/util/finally.hh"
#include "nix/util/signals.hh"

#include <emscripten/emscripten.h>

#include <cstdlib>
#include <cstring>
#include <future>
#include <memory>
#include <random>

namespace nix {

const unsigned int RETRY_TIME_MS_DEFAULT = 250;

std::filesystem::path FileTransferSettings::getDefaultSSLCertFile() {
    return "";
}

FileTransferSettings::FileTransferSettings() {}

FileTransferSettings fileTransferSettings;

static GlobalConfig::Register rFileTransferSettings(&fileTransferSettings);

EM_JS(int, libeval_wasm_fetch,
      (const char *urlPtr, int method, const char *expectedETagPtr, char **outData, size_t *outSize,
       char **outUrl, char **outEtag, char **outError),
      {
          // clang-format off: this block is JavaScript embedded in a C++ macro.
          const newUtf8 = value => {
              const text = String(value || "");
              const bytes = new TextEncoder().encode(text);
              const ptr = _malloc(bytes.length + 1);
              HEAPU8.set(bytes, ptr);
              HEAPU8[ptr + bytes.length] = 0;
              return ptr;
          };
          const url = UTF8ToString(urlPtr);
          const expectedETag = expectedETagPtr ? UTF8ToString(expectedETagPtr) : "";
          const methodName = method === 1 ? "HEAD"
              : method === 2 ? "PUT"
              : method === 3 ? "POST"
              : method === 4 ? "DELETE"
              : "GET";
          const archiveExtensions = [
              ".tar",
              ".tar.gz",
              ".tgz",
              ".tar.xz",
              ".txz",
              ".tar.bz2",
              ".tbz2",
              ".tar.zst",
              ".zip",
          ];
          const hasArchiveExtension = parsedUrl => {
              const path = parsedUrl.pathname.toLowerCase();
              return archiveExtensions.some(extension => path.endsWith(extension));
          };
          const archiveInfo = value => {
              try {
                  const parsedUrl = new URL(value);
                  const pathParts = parsedUrl.pathname.split("/").filter(Boolean);
                  const githubArchive =
                      parsedUrl.protocol === "https:" &&
                      parsedUrl.hostname === "github.com" &&
                      pathParts.length >= 4 &&
                      pathParts[2] === "archive";
                  const codeloadArchive =
                      parsedUrl.protocol === "https:" &&
                      parsedUrl.hostname === "codeload.github.com" &&
                      pathParts.length >= 4 &&
                      ["tar.gz", "zip", "legacy.tar.gz", "legacy.zip"].includes(pathParts[2]);
                  const gitlabArchive =
                      parsedUrl.protocol === "https:" &&
                      parsedUrl.hostname.endsWith("gitlab.com") &&
                      (pathParts.includes("archive.tar.gz") ||
                       pathParts.includes("archive.zip") ||
                       (pathParts.includes("-") &&
                        pathParts.includes("archive") &&
                        hasArchiveExtension(parsedUrl)));
                  const sourcehutArchive =
                      parsedUrl.protocol === "https:" &&
                      parsedUrl.hostname.endsWith("git.sr.ht") &&
                      pathParts.includes("archive") &&
                      hasArchiveExtension(parsedUrl);
                  const genericArchive =
                      parsedUrl.protocol === "https:" && hasArchiveExtension(parsedUrl);
                  return {
                      parsedUrl,
                      archive: githubArchive || codeloadArchive || gitlabArchive ||
                          sourcehutArchive || genericArchive,
                  };
              } catch (_) {
                  return { parsedUrl: null, archive: false };
              }
          };
          const parseNetrc = text => {
              const credentials = {};
              const stripQuotes = value => {
                  const text = String(value || "");
                  if (text.length >= 2) {
                      const first = text.charCodeAt(0);
                      const last = text.charCodeAt(text.length - 1);
                      if ((first === 34 && last === 34) || (first === 39 && last === 39))
                          return text.slice(1, -1);
                  }
                  return text;
              };
              const tokens = String(text || "").trim().split(/\\s+/).filter(Boolean);
              let machine = "";
              let login = "";
              for (let index = 0; index < tokens.length; index += 1) {
                  const token = stripQuotes(tokens[index]);
                  if (token === "machine" || token === "default") {
                      machine = token === "default"
                          ? "default"
                          : stripQuotes(tokens[++index]);
                      login = "";
                  } else if (token === "login") {
                      login = stripQuotes(tokens[++index]);
                  } else if (token === "password" && machine) {
                      const password = stripQuotes(tokens[++index]);
                      credentials[machine] = { login, password };
                  }
              }
              return credentials;
          };
          const authorizationFor = (target, netrcText) => {
              const credentials = parseNetrc(netrcText);
              const entry = credentials[target.hostname] || credentials.default;
              if (!entry || !entry.password)
                  return "";
              const user = entry.login || "token";
              return "Basic " + btoa(`${user}:${entry.password}`);
          };
          const targetInfo = archiveInfo(url);
          const fetchConfig = globalThis.LibevalWasmFetchConfig || {};
          const configuredProxy = fetchConfig && fetchConfig.enabled && fetchConfig.proxyUrl;
          const proxyOrigin = value => {
              try {
                  return new URL(value).origin;
              } catch (_) {
                  return "";
              }
          };
          const shouldProxy = Boolean(
              configuredProxy &&
              targetInfo.archive &&
              (!targetInfo.parsedUrl ||
               targetInfo.parsedUrl.origin !== proxyOrigin(configuredProxy))
          );
          try {
              const xhr = new XMLHttpRequest();
              const requestUrl = shouldProxy
                  ? `${fetchConfig.proxyUrl}?url=${encodeURIComponent(url)}`
                  : url;
              xhr.open(methodName, requestUrl, false);
              if (expectedETag)
                  xhr.setRequestHeader("If-None-Match", expectedETag);
              if (shouldProxy && fetchConfig.netrc && targetInfo.parsedUrl) {
                  const auth = authorizationFor(targetInfo.parsedUrl, fetchConfig.netrc);
                  if (auth)
                      xhr.setRequestHeader("X-Upstream-Authorization", auth);
              }
              xhr.overrideMimeType("text/plain; charset=x-user-defined");
              xhr.send(null);

              const response = xhr.responseText || "";
              const size = response.length;
              const dataPtr = size > 0 ? _malloc(size) : 0;
              for (let i = 0; i < size; i += 1)
                  HEAPU8[dataPtr + i] = response.charCodeAt(i) & 0xff;

              const finalUrlPtr = newUtf8(xhr.getResponseHeader("X-Upstream-URL") ||
                  xhr.responseURL || url);
              const etagPtr = newUtf8(xhr.getResponseHeader("ETag") || "");
              HEAPU32[outData >> 2] = dataPtr;
              HEAPU32[outSize >> 2] = size;
              HEAPU32[outUrl >> 2] = finalUrlPtr;
              HEAPU32[outEtag >> 2] = etagPtr;
              HEAPU32[outError >> 2] = 0;
              return xhr.status || 200;
          } catch (error) {
              const githubArchive = targetInfo.archive;
              const hint = githubArchive
                  ? " Archive downloads can be blocked by CORS from ordinary browser pages; enable the standalone archive proxy, use the Python backend, or use a CORS-readable archive mirror."
                  : " This can be caused by CORS, DNS, TLS, offline, or remote-server failures.";
              HEAPU32[outData >> 2] = 0;
              HEAPU32[outSize >> 2] = 0;
              HEAPU32[outUrl >> 2] = newUtf8(url);
              HEAPU32[outEtag >> 2] = 0;
              HEAPU32[outError >> 2] =
                  newUtf8((error && error.message ? error.message : error) + hint);
              return -1;
          }
          // clang-format on
      });

struct MallocString {
    char *ptr = nullptr;

    ~MallocString() {
        std::free(ptr);
    }

    std::string str() const {
        return ptr ? std::string(ptr) : "";
    }
};

struct MallocBytes {
    char *ptr = nullptr;
    size_t size = 0;

    ~MallocBytes() {
        std::free(ptr);
    }

    std::string str() const {
        return ptr && size > 0 ? std::string(ptr, size) : "";
    }
};

std::string displayUri(const FileTransferRequest &request) {
    try {
        auto parsed = request.uri.parsed();
        if (parsed.authority && parsed.authority->user) {
            parsed.authority->user.reset();
            parsed.authority->password.reset();
            return parsed.to_string();
        }
    } catch (BadURL &) {
    }
    return request.uri.to_string();
}

FileTransferResult performBrowserTransfer(const FileTransferRequest &request) {
    if (request.method != HttpMethod::Get && request.method != HttpMethod::Head)
        throw FileTransferError(FileTransfer::Misc, std::nullopt,
                                "libeval-wasm only supports GET and HEAD transfers for '%s'",
                                displayUri(request));

    char *data = nullptr;
    size_t dataSize = 0;
    char *finalUrl = nullptr;
    char *etag = nullptr;
    char *error = nullptr;
    int method = request.method == HttpMethod::Head ? 1 : 0;
    int status =
        libeval_wasm_fetch(request.uri.to_string().c_str(), method,
                           request.expectedETag.empty() ? nullptr : request.expectedETag.c_str(),
                           &data, &dataSize, &finalUrl, &etag, &error);

    MallocBytes body{data, dataSize};
    MallocString effectiveUrl{finalUrl};
    MallocString etagValue{etag};
    MallocString errorValue{error};

    if (status < 0)
        throw FileTransferError(FileTransfer::Misc, std::nullopt,
                                "libeval-wasm fetch failed for '%s': %s", displayUri(request),
                                errorValue.str());

    FileTransferResult result;
    result.urls.push_back(effectiveUrl.str().empty() ? request.uri.to_string()
                                                     : effectiveUrl.str());
    result.etag = etagValue.str();
    result.cached = status == 304;
    result.bodySize = dataSize;

    if (!result.cached && request.method == HttpMethod::Get) {
        auto payload = body.str();
        result.bodySize = payload.size();
        if (request.dataCallback) {
            request.dataCallback(payload);
        } else {
            result.data = std::move(payload);
        }
    }

    if (status >= 400)
        throw FileTransferError(status == 404 ? FileTransfer::NotFound : FileTransfer::Misc,
                                result.data, "unable to download '%s': HTTP status %d",
                                displayUri(request), status);

    return result;
}

struct BrowserFileTransfer : FileTransfer {
    struct BrowserItem : Item {};

    ItemHandle enqueueFileTransfer(const FileTransferRequest &request,
                                   Callback<FileTransferResult> callback) override {
        auto item = std::make_shared<BrowserItem>();
        try {
            callback(performBrowserTransfer(request));
        } catch (...) {
            callback.rethrow();
        }
        return ItemHandle{item};
    }

    void unpauseTransfer(ItemHandle) override {}
};

static auto *const fileTransfer = new std::shared_ptr<BrowserFileTransfer>;

ref<FileTransfer> getFileTransfer() {
    if (!*fileTransfer)
        *fileTransfer = make_ref<BrowserFileTransfer>().get_ptr();
    return ref<FileTransfer>(*fileTransfer);
}

ref<FileTransfer> makeFileTransfer(const FileTransferSettings &) {
    return make_ref<BrowserFileTransfer>();
}

void FileTransferRequest::setupForS3() {
    auto parsedS3 = ParsedS3URL::parse(uri.parsed());
    uri = parsedS3.toHttpsUrl();
}

std::future<FileTransferResult>
FileTransfer::enqueueFileTransfer(const FileTransferRequest &request) {
    auto promise = std::make_shared<std::promise<FileTransferResult>>();
    enqueueFileTransfer(request, {[promise](std::future<FileTransferResult> fut) {
                            try {
                                promise->set_value(fut.get());
                            } catch (...) {
                                promise->set_exception(std::current_exception());
                            }
                        }});
    return promise->get_future();
}

FileTransferResult FileTransfer::download(const FileTransferRequest &request) {
    return enqueueFileTransfer(request).get();
}

FileTransferResult FileTransfer::upload(const FileTransferRequest &request) {
    return enqueueFileTransfer(request).get();
}

FileTransferResult FileTransfer::deleteResource(const FileTransferRequest &request) {
    return enqueueFileTransfer(request).get();
}

void FileTransfer::download(FileTransferRequest &&request, Sink &sink,
                            std::function<void(FileTransferResult)> resultCallback) {
    auto result = download(request);
    if (!result.data.empty())
        sink(result.data);
    if (resultCallback)
        resultCallback(std::move(result));
}

template <typename... Args>
FileTransferError::FileTransferError(FileTransfer::Error error, std::optional<std::string> response,
                                     const Args &...args)
    : CloneableError(args...), error(error), response(response) {
    const auto hf = HintFmt(args...);
    if (response && (response->size() < 1024 || response->find("<html>") != std::string::npos))
        err.msg = HintFmt("%1%\n\nresponse body:\n\n%2%", Uncolored(hf.str()), chomp(*response));
    else
        err.msg = hf;
}

} // namespace nix
