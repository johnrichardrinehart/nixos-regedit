# NixOS Regedit

Single-page browser for NixOS module options, presented with a Registry Editor-style interface.

Build it with:

```sh
nix build --builders ''
```

Then open `result/index.html` in a browser.

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

The browser UI does not call an HTTP backend. Evaluation is expected to be provided by a WASI evaluator exposed as `window.NixOSRegeditWasiEvaluator`.
