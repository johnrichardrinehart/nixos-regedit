import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tools.build_standalone import inline_script
from tools.build_standalone import main as build_standalone


class StaticBundleTests(unittest.TestCase):
    def test_app_has_no_http_backend_calls(self):
        app = Path("nixos_regedit/static/app.js").read_text()
        self.assertNotIn("/api/", app)
        self.assertNotIn("fetch(", app)
        self.assertIn("window.NixOSRegeditWasiEvaluator", app)
        self.assertIn("WASI evaluator unavailable", app)
        index = Path("nixos_regedit/static/index.html").read_text()
        self.assertIn("evaluator-loader.js", index)

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

    def test_standalone_script_inlining_hides_raw_script_bytes(self):
        html = inline_script('globalThis.marker = "</script><script>bad</script>";\0', "test.js")
        self.assertIn("atob(", html)
        self.assertIn("sourceURL=test.js", html)
        self.assertNotIn("globalThis.marker", html)
        self.assertEqual(html.count("</script>"), 1)


if __name__ == "__main__":
    unittest.main()
