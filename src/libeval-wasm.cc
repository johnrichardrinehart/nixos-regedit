#include <nix_api_expr.h>
#include <nix_api_flake.h>
#include <nix_api_store.h>
#include <nix_api_util.h>
#include <nix_api_value.h>

#include <emscripten/emscripten.h>

#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <vector>

extern "C" {

int MD5_Init(void *) {
    return 1;
}

int MD5_Update(void *, const void *, unsigned long) {
    return 1;
}

int MD5_Final(unsigned char *md, void *) {
    std::memset(md, 0, 16);
    return 1;
}

int SHA1_Init(void *) {
    return 1;
}

int SHA1_Update(void *, const void *, unsigned long) {
    return 1;
}

int SHA1_Final(unsigned char *md, void *) {
    std::memset(md, 0, 20);
    return 1;
}

int SHA256_Init(void *) {
    return 1;
}

int SHA256_Update(void *, const void *, unsigned long) {
    return 1;
}

int SHA256_Final(unsigned char *md, void *) {
    std::memset(md, 0, 32);
    return 1;
}

int SHA512_Init(void *) {
    return 1;
}

int SHA512_Update(void *, const void *, unsigned long) {
    return 1;
}

int SHA512_Final(unsigned char *md, void *) {
    std::memset(md, 0, 64);
    return 1;
}

int sodium_init(void) {
    return 0;
}

void randombytes_buf(void *buf, unsigned long size) {
    std::memset(buf, 0, size);
}

struct blake3_hasher;

void blake3_hasher_update(blake3_hasher *self, const void *input, size_t input_len);

void blake3_hasher_update_tbb(blake3_hasher *self, const void *input, size_t input_len) {
    blake3_hasher_update(self, input, input_len);
}

int crypto_sign_detached(unsigned char *sig, unsigned long long *siglen, const unsigned char *,
                         unsigned long long, const unsigned char *) {
    if (sig)
        std::memset(sig, 0, 64);
    if (siglen)
        *siglen = 64;
    return -1;
}

int crypto_sign_ed25519_sk_to_pk(unsigned char *pk, const unsigned char *) {
    if (pk)
        std::memset(pk, 0, 32);
    return -1;
}

int crypto_sign_verify_detached(const unsigned char *, const unsigned char *, unsigned long long,
                                const unsigned char *) {
    return -1;
}

int curl_global_init(long) {
    return 0;
}

void *curl_easy_init(void) {
    return nullptr;
}

void curl_easy_cleanup(void *) {}

void curl_easy_reset(void *) {}

int curl_easy_setopt(void *, int, ...) {
    return 0;
}

int curl_easy_getinfo(void *, int, ...) {
    return 0;
}

const char *curl_easy_strerror(int) {
    return "curl unavailable in libeval-wasm";
}

void *curl_multi_init(void) {
    return nullptr;
}

int curl_multi_add_handle(void *, void *) {
    return 0;
}

int curl_multi_remove_handle(void *, void *) {
    return 0;
}

int curl_multi_perform(void *, int *) {
    return 0;
}

int curl_multi_poll(void *, void *, unsigned int, int, int *) {
    return 0;
}

int curl_multi_wakeup(void *) {
    return 0;
}

void *curl_multi_info_read(void *, int *msgs) {
    if (msgs)
        *msgs = 0;
    return nullptr;
}

int curl_multi_setopt(void *, int, ...) {
    return 0;
}

const char *curl_multi_strerror(int) {
    return "curl unavailable in libeval-wasm";
}

int curl_multi_cleanup(void *) {
    return 0;
}

int curl_easy_pause(void *, int) {
    return 0;
}

void *curl_slist_append(void *, const char *) {
    return nullptr;
}

void curl_slist_free_all(void *) {}
}

namespace {

struct OwnedContext {
    nix_c_context *ptr = nix_c_context_create();

    OwnedContext() = default;

    ~OwnedContext() {
        if (ptr)
            nix_c_context_free(ptr);
    }

    OwnedContext(const OwnedContext &) = delete;
    OwnedContext &operator=(const OwnedContext &) = delete;
};

void appendString(const char *start, unsigned int n, void *userData) {
    static_cast<std::string *>(userData)->append(start, n);
}

std::string errorMessage(nix_c_context *ctx) {
    if (!ctx)
        return "unknown Nix C API error";
    unsigned int size = 0;
    const char *message = nix_err_msg(nullptr, ctx, &size);
    if (!message)
        return "unknown Nix C API error";
    return std::string(message, size);
}

bool ok(nix_c_context *ctx, nix_err code, std::string &error, const char *action) {
    if (code == NIX_OK)
        return true;
    error = std::string(action) + ": " + errorMessage(ctx);
    return false;
}

std::string jsonString(const std::string &input) {
    std::string output = "\"";
    for (char c : input) {
        switch (c) {
        case '\\':
            output += "\\\\";
            break;
        case '"':
            output += "\\\"";
            break;
        case '\n':
            output += "\\n";
            break;
        case '\r':
            output += "\\r";
            break;
        case '\t':
            output += "\\t";
            break;
        default:
            const auto byte = static_cast<unsigned char>(c);
            if (byte < 0x20) {
                output += "\\u00";
                constexpr char hex[] = "0123456789abcdef";
                output += hex[(byte >> 4) & 0xf];
                output += hex[byte & 0xf];
            } else {
                output += c;
            }
        }
    }
    output += "\"";
    return output;
}

std::string failure(const std::string &message) {
    return "{\"ok\":false,\"error\":" + jsonString(message) + ",\"attempts\":[]}";
}

std::string evaluateToJson(const std::string &expression) {
    if (expression.empty())
        return failure("missing expression");

    setenv("HOME", "/persist/home", 1);
    setenv("TMPDIR", "/persist/tmp", 1);
    setenv("XDG_CACHE_HOME", "/persist/cache", 1);
    setenv("XDG_CONFIG_HOME", "/persist/config", 1);
    setenv("XDG_DATA_HOME", "/persist/share", 1);
    setenv("XDG_STATE_HOME", "/persist/state", 1);
    setenv("NIX_CACHE_HOME", "/persist/cache/nix", 1);
    setenv("NIX_CONFIG_HOME", "/persist/config/nix", 1);
    setenv("NIX_DATA_HOME", "/persist/share/nix", 1);
    setenv("NIX_STATE_HOME", "/persist/state/nix", 1);
    setenv("NIX_STATE_DIR", "/persist/state/nix/var/nix", 1);
    setenv("NIX_LOG_DIR", "/persist/state/nix/var/log/nix", 1);
    setenv("NIX_STORE_DIR", "/nix/store", 1);

    OwnedContext ctx;
    if (!ctx.ptr)
        return failure("could not allocate Nix C API context");

    std::string error;
    if (!ok(ctx.ptr, nix_libutil_init(ctx.ptr), error, "initializing Nix utilities"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "extra-experimental-features", "nix-command flakes"),
            error, "enabling flakes"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "use-sqlite-wal", "false"), error,
            "configuring SQLite journaling"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "fsync-metadata", "false"), error,
            "configuring metadata sync"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "fsync-store-paths", "false"), error,
            "configuring store sync"))
        return failure(error);
    if (!ok(ctx.ptr, nix_libstore_init(ctx.ptr), error, "initializing Nix store"))
        return failure(error);
    if (!ok(ctx.ptr, nix_libexpr_init(ctx.ptr), error, "initializing Nix evaluator"))
        return failure(error);

    const char *rootParam[] = {"root", "/persist/nix-root"};
    const char *requireSigsParam[] = {"require-sigs", "false"};
    const char **storeParams[] = {rootParam, requireSigsParam, nullptr};
    Store *store = nix_store_open(ctx.ptr, "local", storeParams);
    if (!store)
        return failure("opening persistent browser Nix store: " + errorMessage(ctx.ptr));

    nix_eval_state_builder *builder = nix_eval_state_builder_new(ctx.ptr, store);
    if (!builder) {
        std::string message = "creating Nix eval state builder: " + errorMessage(ctx.ptr);
        nix_store_free(store);
        return failure(message);
    }

    nix_flake_settings *flakeSettings = nix_flake_settings_new(ctx.ptr);
    if (!flakeSettings) {
        std::string message = "creating flake settings: " + errorMessage(ctx.ptr);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return failure(message);
    }
    if (!ok(ctx.ptr, nix_flake_settings_add_to_eval_state_builder(ctx.ptr, flakeSettings, builder),
            error, "registering flake primops")) {
        nix_flake_settings_free(flakeSettings);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return failure(error);
    }

    if (!ok(ctx.ptr, nix_eval_state_builder_load(ctx.ptr, builder), error,
            "loading evaluator settings")) {
        nix_flake_settings_free(flakeSettings);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return failure(error);
    }

    const char *lookupPath[] = {nullptr};
    if (!ok(ctx.ptr, nix_eval_state_builder_set_lookup_path(ctx.ptr, builder, lookupPath), error,
            "setting lookup path")) {
        nix_flake_settings_free(flakeSettings);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return failure(error);
    }

    EvalState *state = nix_eval_state_build(ctx.ptr, builder);
    nix_flake_settings_free(flakeSettings);
    nix_eval_state_builder_free(builder);
    if (!state) {
        std::string message = "creating Nix eval state: " + errorMessage(ctx.ptr);
        nix_store_free(store);
        return failure(message);
    }

    nix_value *value = nix_alloc_value(ctx.ptr, state);
    if (!value) {
        std::string message = "allocating Nix value: " + errorMessage(ctx.ptr);
        nix_state_free(state);
        nix_store_free(store);
        return failure(message);
    }

    const std::string jsonExpression = "builtins.toJSON (" + expression + ")";
    if (!ok(ctx.ptr, nix_expr_eval_from_string(ctx.ptr, state, jsonExpression.c_str(), ".", value),
            error, "evaluating expression")) {
        nix_value_decref(ctx.ptr, value);
        nix_state_free(state);
        nix_store_free(store);
        return failure(error);
    }

    std::string json;
    if (!ok(ctx.ptr, nix_get_string(ctx.ptr, value, appendString, &json), error,
            "extracting JSON string")) {
        nix_value_decref(ctx.ptr, value);
        nix_state_free(state);
        nix_store_free(store);
        return failure(error);
    }

    nix_value_decref(ctx.ptr, value);
    nix_state_free(state);
    nix_store_free(store);
    return json;
}

} // namespace

extern "C" {

EMSCRIPTEN_KEEPALIVE
const char *libeval_wasm(const char *expression) {
    static std::string result;
    try {
        result = evaluateToJson(expression ? expression : "");
    } catch (const std::exception &e) {
        result = failure(std::string("uncaught evaluator exception: ") + e.what());
    } catch (...) {
        result = failure("uncaught evaluator exception");
    }
    return result.c_str();
}

EMSCRIPTEN_KEEPALIVE
const char *libeval_wasm_current_system() {
    return "x86_64-linux";
}
}
