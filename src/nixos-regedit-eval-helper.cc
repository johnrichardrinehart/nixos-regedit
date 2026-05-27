#include <nix_api_expr.h>
#include <nix_api_flake.h>
#include <nix_api_store.h>
#include <nix_api_util.h>
#include <nix_api_value.h>

#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>

namespace {

struct OwnedContext {
    nix_c_context * ptr = nix_c_context_create();

    OwnedContext() = default;

    ~OwnedContext()
    {
        if (ptr)
            nix_c_context_free(ptr);
    }

    OwnedContext(const OwnedContext &) = delete;
    OwnedContext & operator=(const OwnedContext &) = delete;
};

void appendString(const char * start, unsigned int n, void * userData)
{
    static_cast<std::string *>(userData)->append(start, n);
}

std::string errorMessage(nix_c_context * ctx)
{
    if (!ctx)
        return "unknown Nix C API error";
    unsigned int size = 0;
    const char * message = nix_err_msg(nullptr, ctx, &size);
    if (!message)
        return "unknown Nix C API error";
    return std::string(message, size);
}

bool ok(nix_c_context * ctx, nix_err code, const char * action)
{
    if (code == NIX_OK)
        return true;
    std::cerr << action << ": " << errorMessage(ctx) << "\n";
    return false;
}

bool optionalSetting(nix_c_context * ctx, const char * key, const char * value, const char * action)
{
    nix_err code = nix_setting_set(ctx, key, value);
    if (code == NIX_OK || code == NIX_ERR_KEY)
        return true;
    return ok(ctx, code, action);
}

std::string readStdin()
{
    std::ostringstream buffer;
    buffer << std::cin.rdbuf();
    return buffer.str();
}

std::vector<std::string> splitLookupPath(const char * value)
{
    std::vector<std::string> entries;
    if (!value)
        return entries;
    std::string input(value);
    size_t start = 0;
    while (start <= input.size()) {
        size_t end = input.find(':', start);
        std::string entry = input.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (!entry.empty())
            entries.push_back(entry);
        if (end == std::string::npos)
            break;
        start = end + 1;
    }
    return entries;
}

} // namespace

int main(int argc, char ** argv)
{
    bool offline = false;
    const char * cwd = ".";
    const char * storeUri = nullptr;

    for (int index = 1; index < argc; index += 1) {
        if (std::strcmp(argv[index], "--offline") == 0) {
            offline = true;
        } else if (std::strcmp(argv[index], "--cwd") == 0 && index + 1 < argc) {
            cwd = argv[++index];
        } else if (std::strcmp(argv[index], "--store") == 0 && index + 1 < argc) {
            storeUri = argv[++index];
        } else {
            std::cerr << "usage: nixos-regedit-eval-helper [--offline] [--cwd PATH] [--store URI]\n";
            return 2;
        }
    }

    const std::string expression = readStdin();
    if (expression.empty()) {
        std::cerr << "missing expression on stdin\n";
        return 2;
    }

    OwnedContext ctx;
    if (!ctx.ptr) {
        std::cerr << "could not allocate Nix C API context\n";
        return 1;
    }

    if (!ok(ctx.ptr, nix_libutil_init(ctx.ptr), "initializing Nix utilities"))
        return 1;

    if (!ok(ctx.ptr, nix_setting_set(ctx.ptr, "extra-experimental-features", "nix-command flakes"), "enabling flakes"))
        return 1;

    if (!ok(ctx.ptr, nix_libstore_init(ctx.ptr), "initializing Nix store"))
        return 1;

    if (!ok(ctx.ptr, nix_libexpr_init(ctx.ptr), "initializing Nix evaluator"))
        return 1;
    if (offline) {
        if (!optionalSetting(ctx.ptr, "substitute", "false", "disabling substitutes"))
            return 1;
        if (!optionalSetting(ctx.ptr, "tarball-ttl", "4294967295", "preserving cached tarballs"))
            return 1;
        if (!optionalSetting(ctx.ptr, "download-attempts", "0", "disabling downloads"))
            return 1;
    }

    Store * store = nix_store_open(ctx.ptr, storeUri, nullptr);
    if (!store) {
        std::cerr << "opening Nix store: " << errorMessage(ctx.ptr) << "\n";
        return 1;
    }

    nix_eval_state_builder * builder = nix_eval_state_builder_new(ctx.ptr, store);
    if (!builder) {
        std::cerr << "creating Nix eval state builder: " << errorMessage(ctx.ptr) << "\n";
        nix_store_free(store);
        return 1;
    }
    if (!ok(ctx.ptr, nix_eval_state_builder_load(ctx.ptr, builder), "loading evaluator settings")) {
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return 1;
    }

    nix_flake_settings * flakeSettings = nix_flake_settings_new(ctx.ptr);
    if (!flakeSettings) {
        std::cerr << "creating flake settings: " << errorMessage(ctx.ptr) << "\n";
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return 1;
    }

    if (!ok(ctx.ptr, nix_flake_settings_add_to_eval_state_builder(ctx.ptr, flakeSettings, builder), "enabling flakes in evaluator")) {
        nix_flake_settings_free(flakeSettings);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return 1;
    }

    auto lookupEntries = splitLookupPath(std::getenv("NIX_PATH"));
    std::vector<const char *> lookupPath;
    lookupPath.reserve(lookupEntries.size() + 1);
    for (const auto & entry : lookupEntries)
        lookupPath.push_back(entry.c_str());
    lookupPath.push_back(nullptr);
    if (!ok(ctx.ptr, nix_eval_state_builder_set_lookup_path(ctx.ptr, builder, lookupPath.data()), "setting lookup path")) {
        nix_flake_settings_free(flakeSettings);
        nix_eval_state_builder_free(builder);
        nix_store_free(store);
        return 1;
    }

    EvalState * state = nix_eval_state_build(ctx.ptr, builder);
    nix_flake_settings_free(flakeSettings);
    nix_eval_state_builder_free(builder);
    if (!state) {
        std::cerr << "creating Nix eval state: " << errorMessage(ctx.ptr) << "\n";
        nix_store_free(store);
        return 1;
    }

    nix_value * value = nix_alloc_value(ctx.ptr, state);
    if (!value) {
        std::cerr << "allocating Nix value: " << errorMessage(ctx.ptr) << "\n";
        nix_state_free(state);
        nix_store_free(store);
        return 1;
    }

    const std::string jsonExpression = "builtins.toJSON (" + expression + ")";
    if (!ok(ctx.ptr, nix_expr_eval_from_string(ctx.ptr, state, jsonExpression.c_str(), cwd, value), "evaluating expression")) {
        nix_value_decref(ctx.ptr, value);
        nix_state_free(state);
        nix_store_free(store);
        return 1;
    }

    std::string json;
    if (!ok(ctx.ptr, nix_get_string(ctx.ptr, value, appendString, &json), "extracting JSON string")) {
        nix_value_decref(ctx.ptr, value);
        nix_state_free(state);
        nix_store_free(store);
        return 1;
    }

    std::cout << json << "\n";

    nix_value_decref(ctx.ptr, value);
    nix_state_free(state);
    nix_store_free(store);
    return 0;
}
