(function () {
  const FLAKE_REF_RE = /^[A-Za-z0-9+._:/?=@%~-]+(?:#[A-Za-z0-9+._/?=@%~-]+)?$/;

  function nixString(value) {
    return JSON.stringify(String(value));
  }

  function looksLikePayload(value) {
    return (
      value &&
      typeof value === "object" &&
      value.ok === true &&
      value.options &&
      typeof value.options === "object"
    );
  }

  function failure(error) {
    return { ok: false, error, attempts: [] };
  }

  function looksLikeFlakeRef(value) {
    const stripped = String(value || "").trim();
    if (!stripped || stripped.includes("\n")) return false;
    if (/^(\{|\[|\(|let\s|with\s|rec\s)/.test(stripped)) return false;
    return FLAKE_REF_RE.test(stripped);
  }

  function splitFlakeSelector(value) {
    const stripped = String(value || "").trim();
    const index = stripped.indexOf("#");
    if (index < 0) {
      return { explicit: false, ref: stripped, selector: ["nixosModules", "default"] };
    }
    const selector = stripped
      .slice(index + 1)
      .split(".")
      .map((part) => part.trim())
      .filter(Boolean);
    return {
      explicit: true,
      ref: stripped.slice(0, index),
      selector: selector.length ? selector : ["nixosModules", "default"],
    };
  }

  function flakeSelectorLookupExpression(selector) {
    const nixList = `[ ${selector.map((part) => nixString(part)).join(" ")} ]`;
    return `(builtins.foldl' (
      state: name:
        if state.found && builtins.isAttrs state.value && builtins.hasAttr name state.value
        then { found = true; value = builtins.getAttr name state.value; }
        else { found = false; value = null; }
    ) { found = true; value = flake; } ${nixList})`;
  }

  function flakeSelectorExpression(selector) {
    const selected = flakeSelectorLookupExpression(selector);
    return `(let selected = ${selected}; in if selected.found then selected.value else throw "Selected flake output does not exist.")`;
  }

  function browserModuleExpression(expression, system) {
    const flakeRef = looksLikeFlakeRef(expression) ? String(expression || "").trim() : null;
    const selectedFlake = flakeRef ? splitFlakeSelector(flakeRef) : null;
    const selectedDefault = flakeSelectorLookupExpression(["nixosModules", "default"]);
    const inputExpression = selectedFlake
      ? selectedFlake.explicit
        ? flakeSelectorExpression(selectedFlake.selector)
        : `(let selected = ${selectedDefault}; in if selected.found then selected.value else [ ])`
      : `(${expression})`;
    const baseModulesExpression =
      selectedFlake && !selectedFlake.explicit
        ? `(let selected = ${selectedDefault}; in
            if selected.found then [ ]
            else if hasFlake && flake ? lib && flake.lib ? nixosSystem then [ ]
            else if builtins.pathExists flakeModuleList then import flakeModuleList
            else throw "Flake does not expose .#nixosModules.default, flake.lib.nixosSystem, or nixos/modules/module-list.nix.")`
        : "[ ]";
    const nixosSystemOptionsExpression =
      selectedFlake && !selectedFlake.explicit
        ? `(let selected = ${selectedDefault}; in
            if selected.found then null
            else if hasFlake && flake ? lib && flake.lib ? nixosSystem
            then (flake.lib.nixosSystem { inherit system; modules = [ ]; }).options
            else null)`
        : "null";
    const moduleSourceExpression = selectedFlake
      ? selectedFlake.explicit
        ? nixString(`flake attribute .#${selectedFlake.selector.join(".")}`)
        : `(let selected = ${selectedDefault}; in
            if selected.found then "flake attribute .#nixosModules.default"
            else if hasFlake && flake ? lib && flake.lib ? nixosSystem then "flake.lib.nixosSystem"
            else "nixos/modules/module-list.nix")`
      : nixString("input expression");
    return `
let
  system = ${system ? nixString(system) : "builtins.currentSystem"};
  flake = ${selectedFlake ? `builtins.getFlake ${nixString(selectedFlake.ref)}` : "null"};
  hasFlake = flake != null;
  concatStringsSep = sep: list:
    builtins.concatStringsSep sep (map builtins.toString list);
  sanitize = value:
    if builtins.isFunction value then "<function>"
    else if builtins.isPath value then builtins.toString value
    else if builtins.isList value then map sanitize value
    else if builtins.isAttrs value then
      if (value.type or null) == "derivation" then value.name or "<derivation>"
      else if value ? outPath then
        let coerced = builtins.tryEval (builtins.toString value);
        in if coerced.success then coerced.value else value.name or "<path>"
      else builtins.mapAttrs (_: sanitize) value
    else value;
  typeName = type:
    if builtins.isString type then type
    else if builtins.isAttrs type && type ? description then type.description
    else if builtins.isAttrs type && type ? name then type.name
    else if builtins.isFunction type then "<function>"
    else builtins.toString type;
  literalExpression = text: { _type = "literalExpression"; text = builtins.toString text; };
  fallbackLib = rec {
    inherit concatStringsSep literalExpression;
    mdDoc = text: text;
    literalMD = text: text;
    optional = cond: value: if cond then [ value ] else [ ];
    optionals = cond: values: if cond then values else [ ];
    mkIf = condition: value: if condition then value else { };
    mkDefault = value: value;
    mkForce = value: value;
    mkMerge = values: builtins.foldl' recursiveUpdate { } values;
    recursiveUpdate = left: right:
      left // builtins.mapAttrs (name: value:
        if builtins.isAttrs value && builtins.isAttrs (left.\${name} or null)
        then recursiveUpdate left.\${name} value
        else value
      ) right;
    mapAttrs = builtins.mapAttrs;
    attrNames = builtins.attrNames;
    attrValues = builtins.attrValues;
    isAttrs = builtins.isAttrs;
    isBool = builtins.isBool;
    isFunction = builtins.isFunction;
    isInt = builtins.isInt;
    isList = builtins.isList;
    isString = builtins.isString;
    types = rec {
      anything = { name = "anything"; description = "anything"; };
      attrs = { name = "attribute set"; description = "attribute set"; };
      bool = { name = "boolean"; description = "boolean"; };
      int = { name = "signed integer"; description = "signed integer"; };
      str = { name = "string"; description = "string"; };
      lines = { name = "strings concatenated with \\\\n"; description = "strings concatenated with \\\\n"; };
      path = { name = "absolute path"; description = "absolute path"; };
      package = { name = "package"; description = "package"; };
      raw = { name = "raw value"; description = "raw value"; };
      listOf = type: { name = "list of " + typeName type; description = "list of " + typeName type; };
      attrsOf = type: { name = "attribute set of " + typeName type; description = "attribute set of " + typeName type; };
      nullOr = type: { name = "null or " + typeName type; description = "null or " + typeName type; };
      enum = values: { name = "one of " + builtins.toJSON (map sanitize values); description = "one of " + builtins.toJSON (map sanitize values); };
      submodule = module: { name = "submodule"; description = "submodule"; };
    };
    mkOption = args: args // { _type = "option"; };
    mkEnableOption = description: mkOption {
      type = types.bool;
      default = false;
      example = true;
      description = "Whether to enable " + builtins.toString description + ".";
    };
  };
  lib =
    if hasFlake && flake ? lib && flake.lib ? evalModules
    then flake.lib
    else fallbackLib;
  fallbackPkgs = {
    inherit lib;
    stdenv = { hostPlatform = { inherit system; }; };
  };
  pkgs =
    if hasFlake && flake ? legacyPackages && builtins.hasAttr system flake.legacyPackages
    then builtins.getAttr system flake.legacyPackages
    else fallbackPkgs;
  flakeModulesPath = if hasFlake && flake ? outPath then flake.outPath + "/nixos/modules" else "/nixos/modules";
  flakeModuleList = flakeModulesPath + "/module-list.nix";
  modulesPath = if builtins.pathExists flakeModulesPath then flakeModulesPath else "/nixos/modules";
  input = ${inputExpression};
  isModule = value:
    builtins.isFunction value
    || builtins.isList value
    || (builtins.isAttrs value && (value ? imports || value ? options || value ? config));
  inputModules =
    if builtins.isList input then input
    else if builtins.isAttrs input && !(isModule input) then builtins.attrValues input
    else [ input ];
  callModule = module:
    if builtins.isFunction module
    then module { inherit lib pkgs modulesPath; config = { }; options = { }; }
    else module;
  flattenModule = module:
    let called = callModule module;
    in if builtins.isList called then builtins.concatMap flattenModule called
       else if builtins.isAttrs called then
         [ called ] ++ builtins.concatMap flattenModule (called.imports or [ ])
       else [ ];
  baseModules = ${baseModulesExpression};
  modules = baseModules ++ inputModules;
  flattenedModules = builtins.concatMap flattenModule inputModules;
  mergeAttrs = builtins.foldl' lib.recursiveUpdate { };
  nixosSystemOptions = ${nixosSystemOptionsExpression};
  rawOptions =
    if nixosSystemOptions != null then
      nixosSystemOptions
    else if lib ? evalModules then
      (lib.evalModules {
        inherit modules;
        specialArgs = { inherit lib pkgs modulesPath; };
      }).options
    else
      mergeAttrs (map (module: module.options or { }) flattenedModules);
  isOption = value: builtins.isAttrs value && (value._type or null) == "option";
  safeSanitize = value:
    let attempted = builtins.tryEval (builtins.deepSeq (sanitize value) (sanitize value));
    in if attempted.success then attempted.value else "<unevaluated>";
  tryField = option: name: fallback:
    if option ? \${name} then
      let attempted = builtins.tryEval option.\${name};
      in if attempted.success then safeSanitize attempted.value else "<unevaluated>"
    else fallback;
  optionPayload = loc: option: {
    declarations = tryField option "declarations" [ "browser-expression" ];
    default = tryField option "defaultText" null;
    description = builtins.toString (tryField option "description" "");
    example = tryField option "exampleText" null;
    loc = loc;
    readOnly = tryField option "readOnly" false;
    relatedPackages = null;
    type =
      let attempted = builtins.tryEval (option.type or lib.types.anything);
      in if attempted.success then typeName attempted.value else "<unevaluated>";
  };
  collect = loc: value:
    if isOption value then [
      { name = concatStringsSep "." loc; value = optionPayload loc value; }
    ]
    else if builtins.isAttrs value then
      builtins.concatLists (map (name: collect (loc ++ [ name ]) value.\${name}) (builtins.attrNames value))
    else [ ];
  pairs = collect [ ] rawOptions;
  options = builtins.listToAttrs pairs;
in {
  ok = true;
  mode = "browser-nixosModules";
  moduleSource = ${moduleSourceExpression};
  optionCount = builtins.length pairs;
  inherit options;
  diagnostics = [ ];
}`;
  }

  function mkdirTree(module, path) {
    if (!module.FS) return;
    const parts = path.split("/").filter(Boolean);
    let current = "";
    for (const part of parts) {
      current += `/${part}`;
      try {
        module.FS.mkdir(current);
      } catch (error) {
        if (!String(error && error.message).includes("File exists")) {
          try {
            module.FS.stat(current);
          } catch (_) {
            throw error;
          }
        }
      }
    }
  }

  function syncfs(module, populate) {
    if (!module.FS || !module.__nixosRegeditPersistentMounted) return Promise.resolve();
    const prior = module.__nixosRegeditSyncQueue || Promise.resolve();
    const next = prior.then(
      () =>
        new Promise((resolve, reject) => {
          module.FS.syncfs(populate, (error) => {
            if (error) reject(error);
            else resolve();
          });
        }),
    );
    module.__nixosRegeditSyncQueue = next.catch(() => {});
    return next;
  }

  async function preparePersistentStorage(module) {
    if (!module.FS) return { enabled: false, reason: "Emscripten FS is unavailable" };

    mkdirTree(module, "/persist");
    const canUseIdbfs =
      typeof indexedDB !== "undefined" &&
      module.IDBFS &&
      typeof module.FS.mount === "function" &&
      typeof module.FS.syncfs === "function";

    if (canUseIdbfs) {
      try {
        module.FS.mount(module.IDBFS, { autoPersist: false }, "/persist");
        module.__nixosRegeditPersistentMounted = true;
      } catch (error) {
        const message = String(error && error.message ? error.message : error);
        if (!message.includes("Mount point is already in use")) throw error;
        module.__nixosRegeditPersistentMounted = true;
      }
    }

    if (module.__nixosRegeditPersistentMounted) {
      await syncfs(module, true);
    }

    [
      "/persist/home",
      "/persist/tmp",
      "/persist/cache",
      "/persist/cache/nix",
      "/persist/config",
      "/persist/config/nix",
      "/persist/nix-root",
      "/persist/nix-root/nix",
      "/persist/nix-root/nix/store",
      "/persist/nix-root/nix/var",
      "/persist/nix-root/nix/var/log",
      "/persist/nix-root/nix/var/log/nix",
      "/persist/nix-root/nix/var/nix",
      "/persist/share",
      "/persist/share/nix",
      "/persist/state",
      "/persist/state/nix",
      "/persist/state/nix/var",
      "/persist/state/nix/var/nix",
      "/persist/state/nix/var/log",
      "/persist/state/nix/var/log/nix",
    ].forEach((path) => mkdirTree(module, path));

    if (module.ENV) {
      module.ENV.HOME = "/persist/home";
      module.ENV.TMPDIR = "/persist/tmp";
      module.ENV.XDG_CACHE_HOME = "/persist/cache";
      module.ENV.XDG_CONFIG_HOME = "/persist/config";
      module.ENV.XDG_DATA_HOME = "/persist/share";
      module.ENV.XDG_STATE_HOME = "/persist/state";
      module.ENV.NIX_CACHE_HOME = "/persist/cache/nix";
      module.ENV.NIX_CONFIG_HOME = "/persist/config/nix";
      module.ENV.NIX_DATA_HOME = "/persist/share/nix";
      module.ENV.NIX_STATE_HOME = "/persist/state/nix";
      module.ENV.NIX_STATE_DIR = "/persist/state/nix/var/nix";
      module.ENV.NIX_LOG_DIR = "/persist/state/nix/var/log/nix";
    }

    await syncfs(module, false);
    return {
      enabled: Boolean(module.__nixosRegeditPersistentMounted),
      backend: module.__nixosRegeditPersistentMounted ? "IDBFS" : "MEMFS",
      mountPoint: "/persist",
      cacheHome: "/persist/cache",
      nixCacheHome: "/persist/cache/nix",
      stateHome: "/persist/state",
      stateDir: "/persist/state/nix/var/nix",
    };
  }

  async function loadEvaluator() {
    const createEvaluator = window.createLibevalWasm;
    if (typeof createEvaluator !== "function") return false;
    const module = await createEvaluator();
    const storage = await preparePersistentStorage(module);
    const evaluateRaw = module.cwrap("libeval_wasm", "string", ["string"]);
    const currentSystemRaw = module.cwrap("libeval_wasm_current_system", "string", []);
    const evalNix = async (expression) => {
      const response = JSON.parse(evaluateRaw(expression));
      await syncfs(module, false);
      return response;
    };
    window.NixOSRegeditEvaluator = {
      storage,
      currentSystem: async () => currentSystemRaw(),
      resolve: async (request) => {
        const input = String(request.expression || "").trim();
        const isFlakeRef = looksLikeFlakeRef(input);
        return {
          ok: true,
          kind: isFlakeRef ? "flake" : "expression",
          identity: input,
          system: request.system || currentSystemRaw(),
        };
      },
      evaluate: async (request) => {
        const system = request.system || currentSystemRaw();
        const rawResponse = await evalNix(request.expression);
        if (looksLikePayload(rawResponse)) return rawResponse;
        const wrappedResponse = await evalNix(browserModuleExpression(request.expression, system));
        if (wrappedResponse && wrappedResponse.ok === false) return wrappedResponse;
        if (looksLikePayload(wrappedResponse)) return wrappedResponse;
        if (rawResponse && rawResponse.ok === false) return rawResponse;
        return failure(
          "libeval-wasm ran the Nix expression, but it did not return a NixOS module, module list, nixosModules attrset, or NixOS Regedit payload.",
        );
      },
    };
    window.dispatchEvent(new CustomEvent("nixos-regedit-evaluator-ready"));
    return true;
  }

  window.NixOSRegeditLoadEvaluator = loadEvaluator;
  loadEvaluator().catch((error) => {
    const detail = error && error.message ? error.message : error;
    window.dispatchEvent(new CustomEvent("nixos-regedit-evaluator-failed", { detail }));
  });
})();
