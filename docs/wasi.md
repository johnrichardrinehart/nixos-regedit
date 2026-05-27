# WASI evaluator status

This branch has a native helper built against Nix's C APIs:

- `nix-expr-c`
- `nix-flake-c`
- `nix-store-c`
- `nix-util-c`

The helper evaluates the same wrapped expressions the UI needs. It also
registers the flake C API so `builtins.getFlake` is available.

## Build attempt

nixpkgs exposes a `pkgsCross.wasi32` cross set with host platform
`wasm32-unknown-wasi`, but the Nix package is not currently available on that
platform.

This command fails at platform validation:

```sh
nix build --builders '' --impure --expr \
  'let flake = builtins.getFlake (toString ./.);
       pkgs = import flake.inputs.nixpkgs { system = builtins.currentSystem; };
   in pkgs.pkgsCross.wasi32.nix.dev' -L
```

Allowing unsupported systems reaches the dependency closure and fails before a
WASI build can start:

```sh
env NIXPKGS_ALLOW_UNSUPPORTED_SYSTEM=1 \
  nix build --builders '' --impure --show-trace --expr \
  'let flake = builtins.getFlake (toString ./.);
       pkgs = import flake.inputs.nixpkgs {
         system = builtins.currentSystem;
         config.allowUnsupportedSystem = true;
       };
   in pkgs.pkgsCross.wasi32.nix.dev' -L
```

Observed blocker:

```text
error: Not sure what configuration to use for wasm32-unknown-wasi
```

The trace reaches `openssl-static-wasm32-unknown-wasi`, pulled through Nix's
static `nix-util` and store closure. Other native-facing pieces in the closure
include `libarchive`, `libcurl`, `sqlite`, `libgit2`, and the Nix store/cache
filesystem model.

## Browser contract

The single-page UI does not attempt an HTTP backend. It expects:

```js
window.NixOSRegeditEvaluator = {
  currentSystem: async () => "x86_64-linux",
  resolve: async ({ expression, allowFetch, system }) => ({
    ok: true,
    kind: "expression",
    identity: expression,
    system,
  }),
  evaluate: async ({ expression, allowFetch, system }) => ({
    ok: true,
    mode: "expression-nixosModules",
    optionCount: 0,
    options: {},
    diagnostics: [],
  }),
};
```

The UI builds its option tree in the browser from returned option docs.

## Emscripten port progress

The current branch now has one browser evaluator target:

- `.#nix-browser-evaluator`: a reusable Emscripten `SINGLE_FILE` module linked
  against Nix's C API closure. It installs
  `share/nix-browser-evaluator/nix-browser-evaluator.js` and exports
  `createNixBrowserEvaluator()`.

See `docs/nix-browser-evaluator.md` for the JavaScript/C ABI and persistent
storage integration contract.

The first direct Nix attempt failed because it linked native Linux shared
objects into an Emscripten link:

```text
wasm-ld: error: unknown file type: .../lib/libnixflakec.so
wasm-ld: error: unknown file type: .../lib/libnixfetchersc.so
wasm-ld: error: unknown file type: .../lib/libnixexprc.so
wasm-ld: error: unknown file type: .../lib/libnixstorec.so
wasm-ld: error: unknown file type: .../lib/libnixutilc.so
```

Instantiating Nix's modular component scope with `emscriptenStdenv` reaches the
next packaging failure:

```sh
nix build --builders '' --impure --expr '
  let
    flake = builtins.getFlake (toString ./.);
    pkgs = import flake.inputs.nixpkgs { system = builtins.currentSystem; };
    nixWasm = pkgs.nix.overrideScope (_final: _prev: {
      stdenv = pkgs.emscriptenStdenv;
    });
  in
    nixWasm.libs.nix-util-c
' -L --print-out-paths
```

That currently fails because nixpkgs' generic Emscripten builder assumes an
Autotools-style `./configure`, while Nix's modular components are Meson
packages:

```text
emconfigure: ./configure --prefix=...
FileNotFoundError: [Errno 2] No such file or directory
```

The next port step is an Emscripten-aware Meson component layer for Nix, not a
native `.so` link or the generic `buildEmscriptenPackage` wrapper.
