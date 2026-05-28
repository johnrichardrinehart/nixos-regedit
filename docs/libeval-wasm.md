# libeval-wasm

`.#libeval-wasm` builds a reusable Emscripten `SINGLE_FILE` JavaScript module
that embeds the Nix evaluator and its browser-compatible dependency closure.

Build it with:

```sh
nix build --builders '' .#libeval-wasm
```

From another flake, consume it as an ordinary package output:

```nix
{
  inputs.nixos-regedit.url = "github:johnrichardrinehart/nixos-regedit";

  outputs = { nixpkgs, nixos-regedit, ... }:
    let
      system = "x86_64-linux";
      libevalWasm = nixos-regedit.packages.${system}.libeval-wasm;
    in {
      packages.${system}.my-app = nixpkgs.legacyPackages.${system}.stdenvNoCC.mkDerivation {
        # Copy ${libevalWasm}/share/libeval-wasm/libeval.js into your app.
      };
    };
}
```

The package installs:

```text
share/libeval-wasm/libeval.js
```

Load that file in a page and instantiate the module:

```html
<script src="libeval.js"></script>
<script>
  const module = await createLibevalWasm();
  const evalNix = module.cwrap("libeval_wasm", "string", ["string"]);
  const currentSystem = module.cwrap("libeval_wasm_current_system", "string", []);

  const response = JSON.parse(evalNix("{ hello = \"world\"; }"));
  console.log(currentSystem(), response);
</script>
```

## ABI

The exported C functions are:

```c
const char * libeval_wasm(const char * expression);
const char * libeval_wasm_current_system(void);
```

`libeval_wasm` takes a Nix expression string and returns a JSON string. It
evaluates `builtins.toJSON (<expression>)`, so callers should pass an expression
whose result can be converted to JSON.

With Emscripten `cwrap`, prefer:

```js
const evalNix = module.cwrap("libeval_wasm", "string", ["string"]);
```

The return type `"string"` tells Emscripten to copy the returned UTF-8
`const char *` into a JavaScript string immediately.

The JavaScript return value is always a string because that is the ABI boundary,
but the value encoded inside the JSON does not have to be a string:

```js
JSON.parse(evalNix("1 + 1")); // 2
JSON.parse(evalNix("true")); // true
JSON.parse(evalNix("[ 1 2 3 ]")); // [1, 2, 3]
JSON.parse(evalNix("{ a = 1; b = false; }")); // { a: 1, b: false }
```

Path values are also serializable, but Nix applies normal path semantics first.
An existing path is copied/coerced to a store path and then encoded as a JSON
string:

```js
JSON.parse(evalNix("./README.md")); // "/nix/store/...-README.md"
```

Path construction still has to produce a path that exists in the evaluator's
filesystem/store. For example, `./foo + "file.txt"` means "the path
`./foofile.txt`"; it fails unless that path exists. If you want string
concatenation, convert explicitly with `toString`.

If evaluation or JSON conversion fails, the evaluator returns a JSON error
object:

```json
{ "ok": false, "error": "..." }
```

The lower-level form also works:

```js
const evalNixPtr = module.cwrap("libeval_wasm", "number", ["string"]);
const ptr = evalNixPtr("builtins.toJSON 1");
const json = module.UTF8ToString(ptr);
```

In that form, `"number"` is the raw pointer value in the WASM heap. Decode it
immediately. The pointer refers to an internal static result buffer and is only
valid until the next evaluator call.

## Storage

Consumers that need persistent fetch/store cache behavior should mount IDBFS and
set the Nix-related environment variables before calling `libeval_wasm`.
NixOS Regedit's `evaluator-loader.js` is one concrete integration example:

- mount IDBFS at `/persist`
- set `HOME`, `TMPDIR`, `XDG_CACHE_HOME`, `NIX_CACHE_HOME`, `NIX_STATE_DIR`,
  and related variables under `/persist`
- call `FS.syncfs(true)` before evaluation and `FS.syncfs(false)` after
  evaluation
