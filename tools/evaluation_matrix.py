#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import quote, urlparse

from nixos_regedit.evaluator import EvaluationRequest, evaluate

DEFAULT_REPOSITORIES = [
    "github:johnrichardrinehart/johnos",
    "github:anduril/jetpack-nixos",
    "github:jmbaur/homelab",
]


def backend_matrix(repositories: list[str], *, timeout: int) -> list[dict[str, object]]:
    results = []
    for repository in repositories:
        payload = evaluate(
            EvaluationRequest(repository, allow_fetch=True, system="x86_64-linux"),
            timeout=timeout,
        )
        option_count = int(payload.get("optionCount") or len(payload.get("options") or {}))
        if option_count <= 0:
            raise AssertionError(f"{repository} backend returned no options")
        results.append(
            {
                "surface": "backend",
                "repository": repository,
                "optionCount": option_count,
                "moduleSource": payload.get("moduleSource"),
            }
        )
    return results


def _recv_exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise EOFError("websocket closed")
        data += chunk
    return data


class DevToolsConnection:
    def __init__(self, websocket_url: str):
        parsed = urlparse(websocket_url)
        if parsed.hostname is None or parsed.port is None:
            raise ValueError(f"invalid websocket URL: {websocket_url}")
        self._socket = socket.create_connection((parsed.hostname, parsed.port), timeout=10)
        self._next_id = 1
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        path = parsed.path + (f"?{parsed.query}" if parsed.query else "")
        host = parsed.hostname
        host_header = f"[{host}]:{parsed.port}" if ":" in host else f"{host}:{parsed.port}"
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host_header}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._socket.sendall(request.encode("utf-8"))
        response = b""
        while b"\r\n\r\n" not in response:
            response += self._socket.recv(4096)
        if b" 101 " not in response.split(b"\r\n", 1)[0]:
            raise RuntimeError(response.decode("utf-8", "replace"))

    def close(self) -> None:
        self._socket.close()

    def call(self, method: str, params: dict[str, object] | None = None, *, timeout: int = 30):
        message_id = self._next_id
        self._next_id += 1
        self._send_frame(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._socket.settimeout(max(0.1, deadline - time.time()))
            try:
                message = json.loads(self._recv_frame())
            except TimeoutError:
                break
            if message.get("id") == message_id:
                if "error" in message:
                    raise RuntimeError(message["error"])
                return message
        raise TimeoutError(method)

    def _send_frame(self, payload: str) -> None:
        data = payload.encode("utf-8")
        header = bytearray([0x81])
        if len(data) < 126:
            header.append(0x80 | len(data))
        elif len(data) < 65536:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", len(data)))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", len(data)))
        mask = os.urandom(4)
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(data))
        self._socket.sendall(bytes(header) + mask + masked)

    def _recv_frame(self) -> str:
        first, second = _recv_exact(self._socket, 2)
        opcode = first & 0x0F
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", _recv_exact(self._socket, 2))[0]
        elif length == 127:
            length = struct.unpack("!Q", _recv_exact(self._socket, 8))[0]
        if second & 0x80:
            mask = _recv_exact(self._socket, 4)
            payload = bytes(
                byte ^ mask[index % 4]
                for index, byte in enumerate(_recv_exact(self._socket, length))
            )
        else:
            payload = _recv_exact(self._socket, length)
        if opcode == 8:
            raise EOFError("websocket closed")
        return payload.decode("utf-8", "replace")


def _targets(port: int) -> list[dict[str, object]]:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=10) as response:
        return json.load(response)


def _connect_page(port: int) -> DevToolsConnection:
    page = next(target for target in _targets(port) if target.get("type") == "page")
    connection = DevToolsConnection(str(page["webSocketDebuggerUrl"]))
    connection.call("Runtime.enable")
    connection.call("Page.enable")
    return connection


def _js_string(value: str) -> str:
    return json.dumps(value)


def standalone_matrix(
    repositories: list[str],
    *,
    index_html: Path,
    timeout: int,
    port: int,
) -> list[dict[str, object]]:
    browser = shutil.which("brave") or shutil.which("chromium") or shutil.which("google-chrome")
    if not browser:
        raise RuntimeError("standalone matrix requires brave, chromium, or google-chrome on PATH")
    if not index_html.exists():
        raise RuntimeError(f"standalone index does not exist: {index_html}")

    profile = Path(tempfile.mkdtemp(prefix="nixos-regedit-matrix-"))
    process = subprocess.Popen(
        [
            browser,
            "--headless=new",
            "--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            index_html.as_uri(),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                _targets(port)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise TimeoutError("browser did not expose CDP")

        results = []
        connection = _connect_page(port)
        try:
            for repository in repositories:
                url = f"{index_html.as_uri()}?expression={quote(repository, safe='')}&fetch=1"
                connection.call("Page.navigate", {"url": url})
                time.sleep(1)
                start_expression = f"""
                  (() => {{
                    const expression = document.getElementById("expressionInput");
                    expression.value = {_js_string(repository)};
                    expression.dispatchEvent(new Event("input", {{ bubbles: true }}));
                    const allow = document.getElementById("allowFetch");
                    allow.checked = true;
                    allow.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    const proxy = document.getElementById("proxyEnabled");
                    if (proxy) {{
                      proxy.checked = true;
                      proxy.dispatchEvent(new Event("change", {{ bubbles: true }}));
                    }}
                    document.getElementById("evaluateButton").click();
                    return document.getElementById("statusText").textContent;
                  }})()
                """
                connection.call(
                    "Runtime.evaluate",
                    {"expression": start_expression, "returnByValue": True},
                    timeout=30,
                )
                try:
                    result = _wait_for_standalone_result(connection, timeout)
                except Exception as error:
                    raise AssertionError(
                        f"{repository} standalone evaluation failed: {error}"
                    ) from error
                if result["optionCount"] <= 0:
                    raise AssertionError(f"{repository} standalone returned no options: {result}")
                results.append({"surface": "standalone", "repository": repository, **result})
        finally:
            connection.close()
        return results
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        shutil.rmtree(profile, ignore_errors=True)


def _wait_for_standalone_result(connection: DevToolsConnection, timeout: int) -> dict[str, object]:
    deadline = time.time() + timeout
    active = ("Evaluating", "Fetching", "Loading", "Resolving")
    expression = """
      (() => {
        document.getElementById("debugLogButton")?.click();
        return {
          status: document.getElementById("statusText")?.textContent || "",
          count: document.getElementById("countText")?.textContent || "",
          rows: document.querySelectorAll("[data-option-name], .option-name, tbody tr").length,
          diagnosticsHidden: document.getElementById("diagnostics")?.hidden,
          diagnostics: (document.getElementById("diagnostics")?.textContent || "").slice(0, 50000),
          debugTail: (document.getElementById("debugLogBody")?.textContent || "").slice(-50000)
        };
      })()
    """
    last = {}
    while time.time() < deadline:
        time.sleep(2)
        payload = connection.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True},
            timeout=30,
        )
        last = payload["result"]["result"].get("value") or {}
        status = str(last.get("status") or "")
        if not any(marker in status for marker in active):
            if status == "Evaluation failed" or last.get("diagnostics"):
                raise AssertionError(last)
            return {
                "status": status,
                "optionCount": _option_count_from_status(status),
                "visibleRows": int(last.get("rows") or 0),
                "diagnosticsHidden": bool(last.get("diagnosticsHidden")),
            }
    raise TimeoutError(f"standalone evaluation did not finish: {last}")


def _option_count_from_status(status: str) -> int:
    marker = status.rsplit(": ", 1)[-1]
    if marker.endswith(" options"):
        return int(marker.removesuffix(" options"))
    raise AssertionError(f"could not parse option count from status: {status}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--surface", choices=["backend", "standalone", "all"], default="all")
    parser.add_argument("--repository", action="append", dest="repositories")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--standalone-index", type=Path, default=Path("result/index.html"))
    parser.add_argument("--port", type=int, default=9230)
    args = parser.parse_args()

    repositories = args.repositories or DEFAULT_REPOSITORIES
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/nixos-regedit-nix-cache")
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

    results = []
    if args.surface in {"backend", "all"}:
        results.extend(backend_matrix(repositories, timeout=args.timeout))
    if args.surface in {"standalone", "all"}:
        results.extend(
            standalone_matrix(
                repositories,
                index_html=args.standalone_index.resolve(),
                timeout=args.timeout,
                port=args.port,
            )
        )
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
