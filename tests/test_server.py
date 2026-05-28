import json
import tempfile
import threading
import unittest
import unittest.mock
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from nixos_regedit import server
from nixos_regedit.server import backend_index, make_handler


class ServerTests(unittest.TestCase):
    def run_server(self, evaluator):
        static_dir = Path(tempfile.mkdtemp())
        static_dir.joinpath("index.html").write_text(
            '<!doctype html><script src="libeval.js"></script>\n'
            '<script src="evaluator-loader.js"></script>',
            encoding="utf-8",
        )
        static_dir.joinpath("backend-loader.js").write_text("window.backend = true;")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(static_dir, evaluator))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def get_json(self, url):
        with urllib.request.urlopen(url) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, url, payload):
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_backend_index_uses_backend_loader(self):
        html = backend_index().decode("utf-8")
        self.assertIn('src="backend-loader.js"', html)
        self.assertNotIn('src="libeval.js"', html)
        self.assertNotIn('src="evaluator-loader.js"', html)
        self.assertNotIn('id="allowFetch"', html)
        self.assertNotIn("Allow fetch", html)
        self.assertNotIn("<h2>Fetching</h2>", html)
        self.assertNotIn('id="standaloneNetworkRow"', html)
        self.assertNotIn('id="proxyUrl"', html)
        self.assertNotIn('id="netrcInput"', html)
        self.assertIn("local Python backend", html)
        self.assertIn("system <code>nix</code>", html)
        self.assertIn("Backend sources", html)

    def test_backend_index_can_seed_initial_expression(self):
        html = backend_index(initial_expression="github:nixos/nixpkgs").decode("utf-8")
        self.assertIn(">github:nixos/nixpkgs</textarea>", html)

    def test_backend_index_can_render_revision(self):
        html = backend_index(revision="rev test123").decode("utf-8")
        self.assertIn(">rev test123</span>", html)

    def test_backend_cli_defaults_to_localhost_dynamic_port(self):
        with unittest.mock.patch("nixos_regedit.server.build_server") as build_server:
            with unittest.mock.patch("nixos_regedit.server.open_browser") as open_browser:
                build_server.return_value.server_address = ("127.0.0.1", 45678)
                build_server.return_value.serve_forever.side_effect = KeyboardInterrupt

                self.assertEqual(server.main(["github:nixos/nixpkgs"]), 0)

        build_server.assert_called_once_with(
            "127.0.0.1",
            0,
            initial_expression="github:nixos/nixpkgs",
        )
        open_browser.assert_called_once_with("http://127.0.0.1:45678")

    def test_health_and_static(self):
        base = self.run_server(lambda payload: {"ok": True, "options": {}, "optionCount": 0})
        health = self.get_json(f"{base}/api/health")
        self.assertTrue(health["ok"])
        self.assertIsInstance(health["system"], str)
        with urllib.request.urlopen(f"{base}/") as response:
            self.assertIn("text/html", response.headers["Content-Type"])

    def test_successful_evaluation_adds_tree(self):
        def evaluator(payload):
            return {
                "ok": True,
                "mode": "expression-nixosModules",
                "optionCount": 1,
                "options": {"demo.enable": {"loc": ["demo", "enable"], "type": "boolean"}},
                "diagnostics": [],
            }

        base = self.run_server(evaluator)
        payload = self.post_json(f"{base}/api/evaluate", {"expression": "{ default = {}; }"})
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["tree"]["children"][0]["name"], "demo")

    def test_failed_validation_returns_diagnostics_shape(self):
        def evaluator(payload):
            raise ValueError("expression is required")

        base = self.run_server(evaluator)
        request = urllib.request.Request(
            f"{base}/api/evaluate",
            data=json.dumps({"allowFetch": False}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        body = json.loads(caught.exception.read().decode("utf-8"))
        self.assertFalse(body["ok"])
        self.assertIn("error", body)
        self.assertIn("attempts", body)


if __name__ == "__main__":
    unittest.main()
