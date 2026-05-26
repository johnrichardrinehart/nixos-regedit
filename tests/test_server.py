import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from nixos_regedit.server import make_handler
from http.server import ThreadingHTTPServer


class ServerTests(unittest.TestCase):
    def run_server(self, evaluator):
        static_dir = Path(tempfile.mkdtemp())
        static_dir.joinpath("index.html").write_text("<!doctype html><title>ok</title>")
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

    def test_health_and_static(self):
        base = self.run_server(lambda payload: {"ok": True, "options": {}, "optionCount": 0})
        self.assertEqual(self.get_json(f"{base}/api/health"), {"ok": True})
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
