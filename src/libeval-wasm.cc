#include <nix_api_expr.h>
#include <nix_api_flake.h>
#include <nix_api_store.h>
#include <nix_api_util.h>
#include <nix_api_value.h>

#include <emscripten/emscripten.h>

#include <array>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <string>
#include <unordered_map>
#include <vector>

namespace {

struct Sha256State {
    std::array<uint32_t, 8> h{};
    std::array<unsigned char, 64> buffer{};
    uint64_t bytes = 0;
    size_t bufferSize = 0;
};

std::unordered_map<void *, Sha256State> sha256States;

uint32_t rotr(uint32_t value, unsigned int bits) {
    return (value >> bits) | (value << (32 - bits));
}

uint32_t load32(const unsigned char *data) {
    return (uint32_t(data[0]) << 24) | (uint32_t(data[1]) << 16) | (uint32_t(data[2]) << 8) |
           uint32_t(data[3]);
}

void store32(unsigned char *out, uint32_t value) {
    out[0] = static_cast<unsigned char>(value >> 24);
    out[1] = static_cast<unsigned char>(value >> 16);
    out[2] = static_cast<unsigned char>(value >> 8);
    out[3] = static_cast<unsigned char>(value);
}

void processSha256Block(Sha256State &state, const unsigned char *block) {
    static constexpr std::array<uint32_t, 64> k = {
        0x428a2f98u, 0x71374491u, 0xb5c0fbcfu, 0xe9b5dba5u, 0x3956c25bu, 0x59f111f1u, 0x923f82a4u,
        0xab1c5ed5u, 0xd807aa98u, 0x12835b01u, 0x243185beu, 0x550c7dc3u, 0x72be5d74u, 0x80deb1feu,
        0x9bdc06a7u, 0xc19bf174u, 0xe49b69c1u, 0xefbe4786u, 0x0fc19dc6u, 0x240ca1ccu, 0x2de92c6fu,
        0x4a7484aau, 0x5cb0a9dcu, 0x76f988dau, 0x983e5152u, 0xa831c66du, 0xb00327c8u, 0xbf597fc7u,
        0xc6e00bf3u, 0xd5a79147u, 0x06ca6351u, 0x14292967u, 0x27b70a85u, 0x2e1b2138u, 0x4d2c6dfcu,
        0x53380d13u, 0x650a7354u, 0x766a0abbu, 0x81c2c92eu, 0x92722c85u, 0xa2bfe8a1u, 0xa81a664bu,
        0xc24b8b70u, 0xc76c51a3u, 0xd192e819u, 0xd6990624u, 0xf40e3585u, 0x106aa070u, 0x19a4c116u,
        0x1e376c08u, 0x2748774cu, 0x34b0bcb5u, 0x391c0cb3u, 0x4ed8aa4au, 0x5b9cca4fu, 0x682e6ff3u,
        0x748f82eeu, 0x78a5636fu, 0x84c87814u, 0x8cc70208u, 0x90befffau, 0xa4506cebu, 0xbef9a3f7u,
        0xc67178f2u};

    std::array<uint32_t, 64> w{};
    for (size_t i = 0; i < 16; ++i)
        w[i] = load32(block + i * 4);
    for (size_t i = 16; i < 64; ++i) {
        const auto s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
        const auto s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }

    auto a = state.h[0];
    auto b = state.h[1];
    auto c = state.h[2];
    auto d = state.h[3];
    auto e = state.h[4];
    auto f = state.h[5];
    auto g = state.h[6];
    auto h = state.h[7];

    for (size_t i = 0; i < 64; ++i) {
        const auto s1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
        const auto ch = (e & f) ^ (~e & g);
        const auto temp1 = h + s1 + ch + k[i] + w[i];
        const auto s0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
        const auto maj = (a & b) ^ (a & c) ^ (b & c);
        const auto temp2 = s0 + maj;
        h = g;
        g = f;
        f = e;
        e = d + temp1;
        d = c;
        c = b;
        b = a;
        a = temp1 + temp2;
    }

    state.h[0] += a;
    state.h[1] += b;
    state.h[2] += c;
    state.h[3] += d;
    state.h[4] += e;
    state.h[5] += f;
    state.h[6] += g;
    state.h[7] += h;
}

} // namespace

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

int SHA256_Init(void *ctx) {
    auto &state = sha256States[ctx];
    state.h = {0x6a09e667u, 0xbb67ae85u, 0x3c6ef372u, 0xa54ff53au,
               0x510e527fu, 0x9b05688cu, 0x1f83d9abu, 0x5be0cd19u};
    state.bytes = 0;
    state.bufferSize = 0;
    return 1;
}

int SHA256_Update(void *ctx, const void *input, unsigned long inputLen) {
    if (!input && inputLen != 0)
        return 0;

    auto iter = sha256States.find(ctx);
    if (iter == sha256States.end()) {
        SHA256_Init(ctx);
        iter = sha256States.find(ctx);
    }

    auto &state = iter->second;
    auto *data = static_cast<const unsigned char *>(input);
    auto len = static_cast<size_t>(inputLen);
    state.bytes += static_cast<uint64_t>(inputLen);

    while (len > 0) {
        const auto available = state.buffer.size() - state.bufferSize;
        const auto chunk = len < available ? len : available;
        std::memcpy(state.buffer.data() + state.bufferSize, data, chunk);
        state.bufferSize += chunk;
        data += chunk;
        len -= chunk;

        if (state.bufferSize == state.buffer.size()) {
            processSha256Block(state, state.buffer.data());
            state.bufferSize = 0;
        }
    }

    return 1;
}

int SHA256_Final(unsigned char *md, void *ctx) {
    if (!md)
        return 0;

    auto iter = sha256States.find(ctx);
    if (iter == sha256States.end()) {
        SHA256_Init(ctx);
        iter = sha256States.find(ctx);
    }

    auto &state = iter->second;
    const auto bitLen = state.bytes * 8;

    state.buffer[state.bufferSize++] = 0x80;
    if (state.bufferSize > 56) {
        while (state.bufferSize < state.buffer.size())
            state.buffer[state.bufferSize++] = 0;
        processSha256Block(state, state.buffer.data());
        state.bufferSize = 0;
    }

    while (state.bufferSize < 56)
        state.buffer[state.bufferSize++] = 0;

    for (size_t i = 0; i < 8; ++i)
        state.buffer[56 + i] = static_cast<unsigned char>(bitLen >> (56 - i * 8));
    processSha256Block(state, state.buffer.data());

    for (size_t i = 0; i < state.h.size(); ++i)
        store32(md + i * 4, state.h[i]);

    sha256States.erase(iter);
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
    // Browser builds cannot run Nix's thread-backed binary-substitution worker.
    // Source fetches still go through the Emscripten file-transfer shim.
    setenv("NIX_CONFIG",
           "tarball-ttl = 900\n"
           "substitute = false\n"
           "substituters =\n"
           "trusted-public-keys =\n",
           1);

    OwnedContext ctx;
    if (!ctx.ptr)
        return failure("could not allocate Nix C API context");

    std::string error;
    if (!ok(ctx.ptr, nix_libutil_init(ctx.ptr), error, "initializing Nix utilities"))
        return failure(error);
    if (!ok(ctx.ptr, nix_set_verbosity(ctx.ptr, NIX_LVL_DEBUG), error, "enabling debug logging"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "substitute", "false"), error,
            "disabling binary substitution"))
        return failure(error);
    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "substituters", ""), error, "disabling substituters"))
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
