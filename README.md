# NixOS Regedit

Single-page browser for NixOS module options, presented with a Registry Editor-style interface.

Build it with:

```sh
nix build --builders ''
```

Then open `result/index.html` in a browser.

To run the local Python-backed server instead:

```sh
nix run
```

`nix run .#backend` is the same server entrypoint. The `.#standalone` package is
the single-file browser artifact, and `.#nix-browser-evaluator` is the reusable
WASM evaluator package embedded by that artifact.

The app accepts one source value: a Nix expression. If the value looks like a flake reference, the evaluator reads its `.#nixosModules` output. Otherwise the expression must evaluate to the same kind of structure: a module, a list of modules, or an attribute set of modules.

Example expression:

```nix
{
  default = { lib, ... }: {
    options.demo.enable = lib.mkEnableOption "demo";
  };
}
```

Fetching is disabled by default. Enable the UI checkbox when a flake reference or expression needs network access.
The backend can use the local `nix` command to fetch ordinary flake sources such
as GitHub. The standalone page is still subject to browser CORS rules, so remote
archives that are not CORS-readable from local pages need the backend app or a
CORS-readable pinned source.

The standalone browser UI does not call an HTTP backend. Evaluation is provided
by the browser evaluator exposed as `window.NixOSRegeditEvaluator`.

## Reusable Browser Evaluator

The Nix evaluator is available separately as:

```sh
nix build --builders '' .#nix-browser-evaluator
```

That package installs `share/nix-browser-evaluator/nix-browser-evaluator.js`.
It is an Emscripten `SINGLE_FILE` module exporting
`createNixBrowserEvaluator()`. Other browser apps can load it and call
`module.cwrap("libeval_wasm", "string", ["string"])` to evaluate a Nix
expression to a JSON string.

NixOS Regedit consumes this package when building the standalone HTML bundle.
See `docs/nix-browser-evaluator.md` for the ABI and storage integration notes.
