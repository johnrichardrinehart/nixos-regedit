#include <emscripten/emscripten.h>

EMSCRIPTEN_KEEPALIVE
const char * nixos_regedit_eval_smoke(const char * request_json)
{
    (void) request_json;
    return "{\"ok\":true,\"kind\":\"expression\",\"identity\":\"smoke\",\"system\":\"x86_64-linux\",\"mode\":\"browser-smoke\",\"optionCount\":1,\"options\":{\"browser.smoke\":{\"loc\":[\"browser\",\"smoke\"],\"type\":\"boolean\",\"default\":{\"_type\":\"literalExpression\",\"text\":\"true\"},\"description\":\"Browser evaluator smoke output.\"}},\"diagnostics\":[]}";
}
