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
        self.assertIn("applySgr", app)
        self.assertIn("evaluating expression", app)
        index = Path("nixos_regedit/static/index.html").read_text()
        self.assertIn("evaluator-loader.js", index)
        self.assertIn("nix-browser-evaluator.js", index)
        self.assertNotIn("nixos-regedit-evaluator.js", index)
        styles = Path("nixos_regedit/static/styles.css").read_text()
        self.assertIn(".diagnostic-red", styles)
        self.assertIn(".diagnostic-magenta", styles)

    def test_standalone_builder_inlines_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp, "index.html")
            argv = [
                "build_standalone.py",
                "--static-dir",
                "nixos_regedit/static",
                "--out",
                str(out),
            ]
            with unittest.mock.patch("sys.argv", argv):
                self.assertEqual(build_standalone(), 0)
            html = out.read_text()
            self.assertIn("<style>", html)
            self.assertIn("<script>", html)
            self.assertNotIn('src="app.js"', html)
            self.assertNotIn('href="styles.css"', html)
            self.assertNotIn('src="evaluator-loader.js"', html)
            self.assertNotIn('src="nix-browser-evaluator.js"', html)
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
