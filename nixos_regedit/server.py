"""Local HTTP server for the NixOS Regedit UI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .evaluator import EvaluationFailure, current_system, evaluate_payload, resolve_payload
from .tree import build_tree

STATIC_DIR = Path(__file__).with_name("static")
MAX_BODY_BYTES = 5 * 1024 * 1024

Evaluator = Callable[[dict[str, Any]], dict[str, Any]]


def backend_index(static_dir: Path = STATIC_DIR) -> bytes:
    html = static_dir.joinpath("index.html").read_text(encoding="utf-8")
    html = html.replace('    <script src="libeval-wasm.js"></script>\n', "")
    html = html.replace(
        '    <script src="evaluator-loader.js"></script>',
        '    <script src="backend-loader.js"></script>',
    )
    html = html.replace(
        "The standalone page does not use an HTTP backend. Evaluation requires a compatible\n"
        "              libeval-wasm integration embedded as\n"
        "              <code>window.NixOSRegeditEvaluator</code>.",
        "This server uses the local Python backend and the system <code>nix</code> command for\n"
        "              evaluation.",
    )
    return html.encode("utf-8")


def make_handler(static_dir: Path = STATIC_DIR, evaluator: Evaluator | None = None):
    evaluator = evaluator or (lambda payload: evaluate_payload(payload, cwd=os.getcwd()))

    class Handler(BaseHTTPRequestHandler):
        server_version = "NixOSRegedit/0.1"

        def do_GET(self) -> None:
            if self.path == "/api/health":
                self._json(200, {"ok": True, "system": current_system()})
                return
            self._static()

        def do_POST(self) -> None:
            if self.path == "/api/resolve":
                try:
                    self._json(200, resolve_payload(self._read_json()))
                except ValueError as exc:
                    self._json(400, {"ok": False, "error": str(exc), "attempts": []})
                except EvaluationFailure as exc:
                    self._json(422, {"ok": False, "error": exc.error, "attempts": exc.attempts})
                return

            if self.path != "/api/evaluate":
                self._json(404, {"ok": False, "error": "not found"})
                return

            try:
                result = evaluator(self._read_json())
                options = result.get("options")
                if isinstance(options, dict):
                    result["tree"] = build_tree(options)
                self._json(200, result)
            except ValueError as exc:
                self._json(400, {"ok": False, "error": str(exc), "attempts": []})
            except EvaluationFailure as exc:
                self._json(422, {"ok": False, "error": exc.error, "attempts": exc.attempts})

        def log_message(self, _format: str, *args: Any) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length > MAX_BODY_BYTES:
                raise ValueError("request body is too large")
            data = self.rfile.read(length)
            try:
                payload = json.loads(data.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON: {exc}") from exc
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, sort_keys=True).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _static(self) -> None:
            request_path = unquote(self.path.split("?", 1)[0])
            if request_path in ("", "/"):
                self._bytes(200, "text/html", backend_index(static_dir))
                return

            relative = request_path.lstrip("/")
            candidate = (static_dir / relative).resolve()
            static_root = static_dir.resolve()
            if (
                os.path.commonpath([candidate, static_root]) != os.fspath(static_root)
                or not candidate.is_file()
            ):
                self._json(404, {"ok": False, "error": "not found"})
                return
            content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
            self._bytes(200, content_type, candidate.read_bytes())

        def _bytes(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return Handler


def build_server(host: str, port: int, *, static_dir: Path = STATIC_DIR) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(static_dir))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    httpd = build_server(args.host, args.port)
    host, port = httpd.server_address
    print(f"nixos-regedit listening on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
