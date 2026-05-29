import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tools.build_standalone import inline_script
from tools.build_standalone import main as build_standalone


class StaticBundleTests(unittest.TestCase):
    def test_app_has_no_http_backend_calls(self):
        app = Path("nixos_regedit/static/app.js").read_text()
        loader = Path("nixos_regedit/static/evaluator-loader.js").read_text()
        self.assertNotIn("/api/", app)
        self.assertNotIn("fetch(", app)
        self.assertNotIn("channels.nixos.org", loader)
        self.assertNotIn("github:nixos/nixpkgs", loader)
        self.assertIn("window.NixOSRegeditEvaluator", app)
        self.assertIn("Evaluator unavailable", app)
        self.assertIn("renderDiagnosticMessage", app)
        self.assertIn("Object.prototype.toString.call(error)", app)
        self.assertIn("renderRelatedPackages", app)
        self.assertIn('link.target = "_blank"', app)
        self.assertIn("applySgr", app)
        self.assertIn("evaluating expression", app)
        self.assertIn("Browser network failure", app)
        self.assertIn("CORS, DNS, TLS, offline, or remote-server failures", app)
        self.assertIn("debugLogButton", app)
        self.assertIn("setDebugLog", app)
        self.assertIn("debugLogFromAttempts", app)
        self.assertIn("openDebugLog", app)
        self.assertIn("abortActiveEvaluation", app)
        self.assertIn("setEvaluationPhase", app)
        self.assertIn("maybeAutoEvaluate", app)
        self.assertIn("Input changed; visible results are from the previous evaluation", app)
        self.assertIn("Resolving changed input; previous results still shown", app)
        self.assertIn("DEFAULT_ARCHIVE_PROXY_URL", app)
        self.assertIn("standaloneFetchConfig", app)
        self.assertIn("const CACHE_TTL_MS = 15 * 60 * 1000", app)
        self.assertIn("request.result.deleteObjectStore(CACHE_STORE)", app)
        self.assertIn("function scheduleCachePut", app)
        self.assertNotIn('params.set("evaluatedExpression"', app)
        self.assertNotIn("const evaluationExpression", app)
        index = Path("nixos_regedit/static/index.html").read_text()
        self.assertIn("evaluator-loader.js", index)
        self.assertIn("libeval.js", index)
        self.assertNotIn("libeval-wasm.js", index)
        self.assertIn('id="moduleSource"', index)
        self.assertIn('id="standaloneNetworkRow"', index)
        self.assertIn('id="proxyUrl"', index)
        self.assertIn('id="netrcInput"', index)
        self.assertNotIn("nixos-regedit-evaluator.js", index)
        self.assertIn("#nixosModules.default", index)
        self.assertIn("flake.lib.nixosSystem", index)
        self.assertIn("nixos/modules/module-list.nix", index)
        self.assertIn("github:owner/repo#foo", index)
        self.assertIn('["nixosModules", "default"]', loader)
        self.assertIn('[ ${selector.map((part) => nixString(part)).join(" ")} ]', loader)
        self.assertIn("flake.lib.nixosSystem", loader)
        self.assertIn("flake.inputs.nixpkgs.lib.nixosSystem", loader)
        self.assertIn("modules = modules", loader)
        self.assertIn("moduleSource =", loader)
        self.assertIn("Flake does not expose .#nixosModules.default", loader)
        self.assertIn("splitFlakeSelector", loader)
        self.assertIn("nixosSystemSource +", loader)
        self.assertIn("modules = .#nixosModules.default", loader)
        self.assertIn("LibevalWasmFetchConfig", loader)
        self.assertIn("isRemoteFlakeRef", loader)
        self.assertNotIn("isRemoteUnpinnedFlakeRef", loader)
        self.assertNotIn("provide a pinned flake URI", loader)
        self.assertIn("Fetch is disabled. Enable Allow fetch", loader)
        self.assertGreaterEqual(loader.count("isRemoteFlakeRef(input)"), 2)
        self.assertIn("const rawResponse = isFlakeRef", loader)
        self.assertIn("module.ENV.NIX_CONFIG", loader)
        self.assertIn("tarball-ttl = 900", loader)
        self.assertIn("show-trace = true", loader)
        self.assertIn("substituters =", loader)
        self.assertIn("clearNixFetchCache", loader)
        self.assertIn("errorMessage(error)", loader)
        self.assertIn("prepareRemoteFlakeEvaluationState", loader)
        self.assertIn("clearStaleFetchState", loader)
        self.assertIn("missingFlakeSourcePaths", loader)
        self.assertIn("removePath", loader)
        self.assertIn("clearing browser Nix cache and state before remote flake evaluation", loader)
        self.assertIn("/persist/nix-root/nix/var/nix", loader)
        self.assertIn("/persist/state/nix/var/nix", loader)
        self.assertIn("shouldRetryAfterClearingFetchCache", loader)
        self.assertIn("NAR hash mismatch", loader)
        self.assertIn("source\\/flake\\.nix", loader)
        self.assertIn("/persist/nix-root/nix/store/", loader)
        self.assertIn('appendWorkerDebugLog("libeval-wasm:error", response.error)', loader)
        self.assertIn('appendLocalDebugLog("libeval-wasm:error", response.error)', loader)
        self.assertIn("showDiagnostics([payload.error, ...attempts])", app)
        self.assertLess(
            app.index("renderEvaluation(payload, { input, preserveState });"),
            app.index("scheduleCachePut(cacheKey, payload);"),
        )
        self.assertIn("Triggered evaluation: preserve state?", index)
        self.assertIn('id="preserveStateOverlay"', index)
        self.assertIn("Standalone evaluation exhausted available memory", index)
        self.assertIn('id="memoryCleanOverlay"', index)
        self.assertIn("captureEvaluationState", app)
        self.assertIn("triggerEvaluation({ useCache: false, restart: true })", app)
        self.assertIn("restoreEvaluationState(preserveState)", app)
        self.assertIn("forceEvaluatorMemoryClean", app)
        self.assertIn("handleMemoryExhaustion", app)
        self.assertIn("loadWorkerEvaluator", loader)
        self.assertIn("NixOSRegeditEvaluatorLoadError", loader)
        self.assertIn("(0, eval)(window.NixOSRegeditStandaloneEvaluatorSource)", loader)
        self.assertIn("Persistent browser storage unavailable", loader)
        self.assertIn("libeval-wasm module ready without persistent browser storage", loader)
        self.assertIn("NixOSRegeditStandaloneEvaluatorSource", loader)
        self.assertIn("new Worker", loader)
        self.assertIn("printErr", loader)
        self.assertIn("attachDebugLog", loader)
        self.assertIn("currentDebugLog", loader)
        self.assertIn("cancel: () =>", loader)
        self.assertIn("const { signal, onDebugLog, onPhase", loader)
        self.assertIn("relatedPackagesDoc", loader)
        self.assertNotIn("relatedPackages = null", loader)
        self.assertNotIn(
            'if (!message.includes("Mount point is already in use")) throw error', loader
        )
        wasm_source = Path("src/libeval-wasm.cc").read_text()
        self.assertNotIn('nix_setting_set(ctx.ptr, "tarball-ttl"', wasm_source)
        self.assertIn('setenv("NIX_CONFIG"', wasm_source)
        self.assertIn("substitute = false", wasm_source)
        self.assertIn("show-trace = true", wasm_source)
        self.assertIn('nix_setting_set(ctx.ptr, "show-trace", "true")', wasm_source)
        self.assertIn("nix::loggerSettings.showTrace = true", wasm_source)
        self.assertIn('nix_setting_set(ctx.ptr, "substitute", "false")', wasm_source)
        self.assertIn('nix_setting_set(ctx.ptr, "substituters", "")', wasm_source)
        self.assertIn("processSha256Block", wasm_source)
        self.assertNotIn("std::memset(md, 0, 32)", wasm_source)
        styles = Path("nixos_regedit/static/styles.css").read_text()
        self.assertIn(".diagnostics", styles)
        self.assertIn("white-space: pre-wrap", styles)
        self.assertIn(".diagnostic-red", styles)
        self.assertIn(".diagnostic-magenta", styles)
        self.assertIn(".standalone-network-row", styles)
        self.assertIn(".expression-row > textarea", styles)
        self.assertIn('.standalone-network-row > input[type="checkbox"]', styles)
        self.assertIn("70vw", styles)
        self.assertIn("60vh", styles)
        self.assertIn("overflow-x: hidden", styles)
        self.assertIn(".content.no-matches", styles)
        self.assertIn("grid-row: 9", styles)
        self.assertIn("grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr)", styles)
        self.assertIn("#revisionText", styles)

    def test_archive_proxy_worker_is_constrained(self):
        worker = Path("infra/cloudflare/workers/archive-proxy.js").read_text()
        self.assertIn("isGitHubArchive", worker)
        self.assertIn("isGitLabArchive", worker)
        self.assertIn("isSourcehutArchive", worker)
        self.assertIn("hasArchiveExtension", worker)
        self.assertIn("ARCHIVE_PROXY_RATE_LIMITER", worker)
        self.assertIn("DEFAULT_APP_URL", worker)
        self.assertIn("shouldRedirectToApp", worker)
        self.assertIn("Response.redirect", worker)
        self.assertIn("X-Upstream-Authorization", worker)
        self.assertIn("X-Upstream-URL", worker)
        self.assertIn("X-NixOS-Regedit-Proxy-Cache", worker)
        self.assertIn("Access-Control-Expose-Headers", worker)
        self.assertIn("headFromCached", worker)
        self.assertIn("cacheableRequest", worker)
        self.assertIn('!request.headers.has("Range")', worker)
        self.assertIn("only HTTPS archive URLs are allowed", worker)
        self.assertNotIn("github-archive-proxy", worker)

    def test_pre_push_matrix_contract_for_backends_and_inputs(self):
        backend_loader = Path("nixos_regedit/static/backend-loader.js").read_text()
        standalone_loader = Path("nixos_regedit/static/evaluator-loader.js").read_text()
        server = Path("nixos_regedit/server.py").read_text()
        app = Path("nixos_regedit/static/app.js").read_text()

        self.assertIn("/api/evaluate-stream", backend_loader)
        self.assertIn("/api/resolve", backend_loader)
        self.assertIn("NixOSRegeditBackend", backend_loader)
        self.assertIn("backendRequest", backend_loader)
        self.assertIn("allowFetch: true", backend_loader)
        self.assertIn("cancel()", backend_loader)
        self.assertIn("backend_index", server)
        self.assertIn("backend-loader.js", server)

        self.assertIn("loadWorkerEvaluator", standalone_loader)
        self.assertIn("browserModuleExpression", standalone_loader)
        self.assertIn("new Worker", standalone_loader)
        self.assertIn("NixOSRegeditStandaloneEvaluatorSource", standalone_loader)

        self.assertIn("looksLikeFlakeRef", standalone_loader)
        self.assertIn('["nixosModules", "default"]', standalone_loader)
        self.assertIn("selectedFlake.explicit", standalone_loader)
        self.assertIn("(${expression})", standalone_loader)

        self.assertIn("triggerEvaluation({ useCache: false, restart: true })", app)
        self.assertIn("abortActiveEvaluation", app)
        self.assertIn("setEvaluationPhase", app)
        self.assertIn("formatLocalDebugTime", app)
        self.assertIn("browserThreadFailureHint", app)
        self.assertIn("evaluatorReadinessPoll", app)
        self.assertIn("markEvaluatorReady", app)
        self.assertIn('elements.status.textContent === "Loading evaluator"', app)
        self.assertIn('classList.toggle("no-matches"', app)
        self.assertIn("collectMemory", app)
        self.assertIn("recycleWorker", standalone_loader)
        self.assertIn("releaseResultRaw", standalone_loader)
        self.assertIn("libeval_wasm_collect", standalone_loader)
        self.assertIn("bytes after result release", standalone_loader)
        self.assertIn(
            "recycling browser evaluator worker after remote flake evaluation", standalone_loader
        )

        matrix = Path("tools/evaluation_matrix.py").read_text()
        for repository in [
            "github:johnrichardrinehart/johnos",
            "github:anduril/jetpack-nixos",
            "github:jmbaur/homelab",
        ]:
            self.assertIn(repository, matrix)
        self.assertIn("backend_matrix", matrix)
        self.assertIn("standalone_matrix", matrix)
        self.assertIn("No options match", app)

    def test_standalone_evaluator_load_survives_storage_denial(self):
        loader = Path("nixos_regedit/static/evaluator-loader.js").read_text()

        self.assertIn("Persistent browser storage unavailable", loader)
        self.assertIn("libeval-wasm module ready without persistent browser storage", loader)
        self.assertIn('backend: "MEMFS"', loader)
        self.assertIn("storage.enabled = false", loader)
        self.assertNotIn(
            'if (!message.includes("Mount point is already in use")) throw error', loader
        )

    def test_libeval_wasm_uses_browser_tolerant_memory_settings(self):
        recipe = Path("nix/libeval-wasm.nix").read_text()
        source = Path("src/libeval-wasm.cc").read_text()
        transfer = Path("nix/emscripten-filetransfer.cc").read_text()

        self.assertIn("nixEmscriptenComponents.libs.nix-util.dev", recipe)
        self.assertIn("nixEmscriptenComponents.emscriptenDeps.boost.dev", recipe)
        self.assertIn("pkgs.nlohmann_json", recipe)
        self.assertIn("-sINITIAL_MEMORY=268435456", recipe)
        self.assertIn("-sMAXIMUM_MEMORY=1073741824", recipe)
        self.assertIn("-sALLOW_MEMORY_GROWTH=1", recipe)
        self.assertIn("-sSTACK_SIZE=134217728", recipe)
        self.assertIn("-sASSERTIONS=0", recipe)
        self.assertIn("_libeval_wasm_release_result", recipe)
        self.assertIn("_libeval_wasm_collect", recipe)
        self.assertIn("_libeval_wasm_heap_size", recipe)
        self.assertNotIn("-sASSERTIONS=2", recipe)
        self.assertIn("libeval_wasm_release_result", source)
        self.assertIn("std::string().swap(lastResult)", source)
        self.assertIn("maybeCollectJsGarbage", source)
        self.assertIn('typeof globalThis.gc === "function"', source)
        self.assertIn("emscripten_get_heap_size", source)
        self.assertIn("const responseHeader = name =>", transfer)
        self.assertIn('(shouldProxy ? responseHeader("X-Upstream-URL") : "")', transfer)

    def test_standalone_falls_back_when_worker_bootstrap_fails(self):
        loader = Path("nixos_regedit/static/evaluator-loader.js").read_text()

        self.assertIn("NixOSRegeditEvaluatorLoadError", loader)
        self.assertIn("(0, eval)(window.NixOSRegeditStandaloneEvaluatorSource)", loader)
        self.assertIn("const createEvaluator = window.createLibevalWasm", loader)

    def test_standalone_builder_inlines_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "index.html")
            evaluator = Path(tmp, "libeval.js")
            evaluator.write_text("globalThis.createLibevalWasm = function () {};", encoding="utf-8")
            argv = [
                "build_standalone.py",
                "--static-dir",
                "nixos_regedit/static",
                "--evaluator-js",
                str(evaluator),
                "--out",
                str(out),
                "--revision",
                "rev test123",
            ]
            with unittest.mock.patch("sys.argv", argv):
                self.assertEqual(build_standalone(), 0)
            html = out.read_text()
            self.assertIn(">rev test123</span>", html)
            self.assertIn("<style>", html)
            self.assertIn("<script>", html)
            self.assertIn("NixOSRegeditStandaloneEvaluatorSource", html)
            self.assertIn("sourceURL=libeval.js", html)
            self.assertNotIn('src="app.js"', html)
            self.assertNotIn('href="styles.css"', html)
            self.assertNotIn('src="evaluator-loader.js"', html)
            self.assertNotIn('src="libeval.js"', html)
            self.assertNotIn("libeval-wasm.wasm", html)
            self.assertIn(' + "\\n//# sourceURL=app.js"', html)
            self.assertNotIn(' + "\n//# sourceURL=app.js"', html)

    def test_standalone_script_inlining_hides_raw_script_bytes(self):
        html = inline_script('globalThis.marker = "</script><script>bad</script>";\0', "test.js")
        self.assertIn("atob(", html)
        self.assertIn("sourceURL=test.js", html)
        self.assertIn(' + "\\n//# sourceURL=test.js"', html)
        self.assertNotIn(' + "\n//# sourceURL=test.js"', html)
        self.assertNotIn("globalThis.marker", html)
        self.assertEqual(html.count("</script>"), 1)

    def test_pages_workflow_deploys_standalone_html(self):
        workflow = Path(".github/workflows/pages.yml").read_text()
        self.assertIn("nix build .#standalone -L --print-out-paths", workflow)
        self.assertIn("cp -L result/index.html public/index.html", workflow)
        self.assertIn("actions/upload-pages-artifact@v3", workflow)
        self.assertIn("actions/deploy-pages@v4", workflow)


if __name__ == "__main__":
    unittest.main()
