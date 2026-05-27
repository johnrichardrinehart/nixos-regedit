#!/usr/bin/env python3
"""Build a single-file static NixOS Regedit page."""

from __future__ import annotations

import argparse
import base64
import json
import re
from pathlib import Path


def inline_asset(html: str, pattern: str, replacement: str) -> str:
    updated, count = re.subn(pattern, lambda _match: replacement, html, count=1, flags=re.MULTILINE)
    if count != 1:
        raise SystemExit(f"missing marker: {pattern}")
    return updated


def inline_script(source: str, source_name: str) -> str:
    # Inline Emscripten output can contain arbitrary bytes encoded as JS text.
    # Base64 keeps the HTML parser away from embedded NULs and script markers.
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    source_url = json.dumps(f"\n//# sourceURL={source_name}")
    return f"""<script>
(() => {{
  const encoded = "{encoded}";
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  (0, eval)(new TextDecoder().decode(bytes) + {source_url});
}})();
</script>"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--static-dir", required=True, type=Path)
    parser.add_argument("--evaluator-js", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    static_dir = args.static_dir
    html = static_dir.joinpath("index.html").read_text(encoding="utf-8")
    css = static_dir.joinpath("styles.css").read_text(encoding="utf-8")
    js = static_dir.joinpath("app.js").read_text(encoding="utf-8")
    loader = static_dir.joinpath("evaluator-loader.js").read_text(encoding="utf-8")
    evaluator_js = args.evaluator_js.read_text(encoding="utf-8") if args.evaluator_js else None

    html = inline_asset(
        html,
        r'<link\s+rel="stylesheet"\s+href="styles\.css"\s*/?>',
        f"<style>\n{css}\n</style>",
    )
    if evaluator_js is None:
        html = re.sub(
            r'\s*<script\s+src="libeval-wasm\.js"></script>',
            "",
            html,
            count=1,
        )
    else:
        html = inline_asset(
            html,
            r'<script\s+src="libeval-wasm\.js"></script>',
            inline_script(evaluator_js, "libeval-wasm.js"),
        )
    html = inline_asset(
        html,
        r'<script\s+src="evaluator-loader\.js"></script>',
        inline_script(loader, "evaluator-loader.js"),
    )
    html = inline_asset(
        html,
        r'<script\s+src="app\.js"></script>',
        inline_script(js, "app.js"),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
