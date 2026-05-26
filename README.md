# NixOS Regedit

Local-only browser for NixOS module options, presented with a Registry Editor-style interface.

Run it with:

```sh
nix run
```

Then open the printed `http://127.0.0.1:8765` URL.

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
