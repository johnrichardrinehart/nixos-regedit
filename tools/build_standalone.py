#!/usr/bin/env python3
"""Build a single-file static NixOS Regedit page."""

from __future__ import annotations

import argparse
import base64
from pathlib import Path


def inline_asset(html: str, marker: str, replacement: str) -> str:
    if marker not in html:
        raise SystemExit(f"missing marker: {marker}")
    return html.replace(marker, replacement)


def inline_script(source: str, source_name: str) -> str:
    # Inline Emscripten output can contain arbitrary bytes encoded as JS text.
    # Base64 keeps the HTML parser away from embedded NULs and script markers.
    encoded = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return f"""<script>
(() => {{
  const encoded = "{encoded}";
  const binary = atob(encoded);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  (0, eval)(new TextDecoder().decode(bytes) + "\\n//# sourceURL={source_name}");
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
        '<link rel="stylesheet" href="styles.css">',
        f"<style>\n{css}\n</style>",
    )
    if evaluator_js is None:
        html = html.replace(
            '<script src="nixos-regedit-evaluator.js"></script>\n    ',
            "",
        )
    else:
        html = inline_asset(
            html,
            '<script src="nixos-regedit-evaluator.js"></script>',
            inline_script(evaluator_js, "nixos-regedit-evaluator.js"),
        )
    html = inline_asset(
        html,
        '<script src="evaluator-loader.js"></script>',
        inline_script(loader, "evaluator-loader.js"),
    )
    html = inline_asset(
        html,
        '<script src="app.js"></script>',
        inline_script(js, "app.js"),
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(html, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
