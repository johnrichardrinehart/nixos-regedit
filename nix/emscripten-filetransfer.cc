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

EM_JS(int, nixos_regedit_browser_fetch,
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
          try {
              const xhr = new XMLHttpRequest();
              xhr.open(methodName, url, false);
              if (expectedETag)
                  xhr.setRequestHeader("If-None-Match", expectedETag);
              xhr.overrideMimeType("text/plain; charset=x-user-defined");
              xhr.send(null);

              const response = xhr.responseText || "";
              const size = response.length;
              const dataPtr = size > 0 ? _malloc(size) : 0;
              for (let i = 0; i < size; i += 1)
                  HEAPU8[dataPtr + i] = response.charCodeAt(i) & 0xff;

              const finalUrlPtr = newUtf8(xhr.responseURL || url);
              const etagPtr = newUtf8(xhr.getResponseHeader("ETag") || "");
              HEAPU32[outData >> 2] = dataPtr;
              HEAPU32[outSize >> 2] = size;
              HEAPU32[outUrl >> 2] = finalUrlPtr;
              HEAPU32[outEtag >> 2] = etagPtr;
              HEAPU32[outError >> 2] = 0;
              return xhr.status || 200;
          } catch (error) {
              HEAPU32[outData >> 2] = 0;
              HEAPU32[outSize >> 2] = 0;
              HEAPU32[outUrl >> 2] = newUtf8(url);
              HEAPU32[outEtag >> 2] = 0;
              HEAPU32[outError >> 2] = newUtf8(error && error.message ? error.message : error);
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
                                "browser evaluator only supports GET and HEAD transfers for '%s'",
                                displayUri(request));

    char *data = nullptr;
    size_t dataSize = 0;
    char *finalUrl = nullptr;
    char *etag = nullptr;
    char *error = nullptr;
    int method = request.method == HttpMethod::Head ? 1 : 0;
    int status = nixos_regedit_browser_fetch(
        request.uri.to_string().c_str(), method,
        request.expectedETag.empty() ? nullptr : request.expectedETag.c_str(), &data, &dataSize,
        &finalUrl, &etag, &error);

    MallocBytes body{data, dataSize};
    MallocString effectiveUrl{finalUrl};
    MallocString etagValue{etag};
    MallocString errorValue{error};

    if (status < 0)
        throw FileTransferError(FileTransfer::Misc, std::nullopt,
                                "browser fetch failed for '%s': %s", displayUri(request),
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
