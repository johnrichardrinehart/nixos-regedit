(function () {
  const FLAKE_REF_RE = /^[A-Za-z0-9+._:/?=@%~-]+(?:#[A-Za-z0-9+._/?=@%~-]+)?$/;
  window.NixOSRegeditStandalone = true;

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

  function isRemoteFlakeRef(value) {
    const selected = splitFlakeSelector(value);
    const ref = selected.ref;
    return /^[A-Za-z][A-Za-z0-9+.-]*:/.test(ref) && !ref.startsWith("path:");
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
            else if nixosSystemLib != null then [ ]
            else if builtins.pathExists flakeModuleList then import flakeModuleList
            else throw "Flake does not expose .#nixosModules.default, flake.lib.nixosSystem, or nixos/modules/module-list.nix.")`
        : "[ ]";
    const nixosSystemOptionsExpression = selectedFlake
      ? `(if nixosSystemLib != null
          then (nixosSystemLib.nixosSystem { inherit system; modules = modules; }).options
          else null)`
      : "null";
    const moduleSourceExpression = selectedFlake
      ? selectedFlake.explicit
        ? `(if nixosSystemSource != null
            then nixosSystemSource + " (modules = .#${selectedFlake.selector.join(".")})"
            else "flake attribute .#${selectedFlake.selector.join(".")}")`
        : `(let selected = ${selectedDefault}; in
            if selected.found && nixosSystemSource != null
            then nixosSystemSource + " (modules = .#nixosModules.default)"
            else if selected.found then "flake attribute .#nixosModules.default"
            else if nixosSystemSource != null then nixosSystemSource
            else "nixos/modules/module-list.nix")`
      : nixString("input expression");
    return `
let
  system = ${system ? nixString(system) : "builtins.currentSystem"};
  flake = ${selectedFlake ? `builtins.getFlake ${nixString(selectedFlake.ref)}` : "null"};
  hasFlake = flake != null;
  concatStringsSep = sep: list:
    builtins.concatStringsSep sep (map builtins.toString list);
  sanitizeN = depth: value:
    if builtins.isFunction value then "<function>"
    else if builtins.isPath value then builtins.toString value
    else if builtins.isList value then
      if depth <= 0 then "<list>"
      else map (sanitizeN (depth - 1)) value
    else if builtins.isAttrs value then
      if (value.type or null) == "derivation" then value.name or "<derivation>"
      else if value ? outPath then
        let coerced = builtins.tryEval (builtins.toString value);
        in if coerced.success then coerced.value else value.name or "<path>"
      else if depth <= 0 then "<attrs>"
      else builtins.mapAttrs (_: sanitizeN (depth - 1)) value
    else value;
  sanitize = sanitizeN 4;
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
  nixosSystemLib =
    if hasFlake && flake ? lib && flake.lib ? nixosSystem
    then flake.lib
    else if hasFlake
      && flake ? inputs
      && flake.inputs ? nixpkgs
      && flake.inputs.nixpkgs ? lib
      && flake.inputs.nixpkgs.lib ? nixosSystem
    then flake.inputs.nixpkgs.lib
    else null;
  nixosSystemSource =
    if hasFlake && flake ? lib && flake.lib ? nixosSystem
    then "flake.lib.nixosSystem"
    else if hasFlake
      && flake ? inputs
      && flake.inputs ? nixpkgs
      && flake.inputs.nixpkgs ? lib
      && flake.inputs.nixpkgs.lib ? nixosSystem
    then "flake.inputs.nixpkgs.lib.nixosSystem"
    else null;
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
  tryRawField = option: name: fallback:
    if option ? \${name} then
      let attempted = builtins.tryEval option.\${name};
      in if attempted.success then attempted.value else fallback
    else fallback;
  docToString = value:
    let attempted = builtins.tryEval (
      if builtins.isString value then value
      else if builtins.isPath value then builtins.toString value
      else if builtins.isAttrs value && value ? text then builtins.toString value.text
      else if builtins.isAttrs value && value ? description && builtins.isString value.description then value.description
      else builtins.toJSON (sanitizeN 2 value)
    );
    in if attempted.success then attempted.value else "<unevaluated>";
  relatedPackageName = package:
    if builtins.isString package then package
    else if builtins.isList package then concatStringsSep "." package
    else if builtins.isAttrs package && package ? name then builtins.toString package.name
    else if builtins.isAttrs package && package ? path then concatStringsSep "." package.path
    else builtins.toString package;
  relatedPackageDoc = package:
    let
      title =
        if builtins.isAttrs package && package ? title
        then builtins.toString package.title + " aka "
        else "";
      name = relatedPackageName package;
      comment =
        if builtins.isAttrs package && package ? comment
        then "\\n\\n  " + builtins.toString package.comment
        else "";
    in "- [" + title + "\`pkgs." + name + "\`](\\n    https://search.nixos.org/packages?show="
       + name + "&sort=relevance&query=" + name + "\\n  )" + comment + "\\n";
  relatedPackagesDoc = packages:
    if builtins.isList packages && packages != [ ]
    then concatStringsSep "" (map relatedPackageDoc packages)
    else null;
  optionPayload = loc: option: {
    declarations = tryField option "declarations" [ "browser-expression" ];
    default = tryField option "defaultText" null;
    description = docToString (tryRawField option "description" "");
    example = tryField option "exampleText" null;
    loc = loc;
    readOnly = tryField option "readOnly" false;
    relatedPackages = relatedPackagesDoc (tryRawField option "relatedPackages" []);
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

  function removeTree(module, path) {
    if (!module.FS) return;
    let entries;
    try {
      entries = module.FS.readdir(path);
    } catch (_) {
      return;
    }
    for (const entry of entries) {
      if (entry === "." || entry === "..") continue;
      const child = `${path}/${entry}`;
      const stat = module.FS.stat(child);
      if (module.FS.isDir(stat.mode)) {
        removeTree(module, child);
        module.FS.rmdir(child);
      } else {
        module.FS.unlink(child);
      }
    }
  }

  async function clearNixFetchCache(module) {
    removeTree(module, "/persist/cache/nix");
    mkdirTree(module, "/persist/cache/nix");
    await syncfs(module, false);
  }

  function shouldRetryAfterClearingFetchCache(response) {
    const message = String((response && response.error) || "");
    return (
      /NAR hash mismatch|got 'sha256-[^']+'|expected 'sha256-[^']+'/i.test(message) ||
      /path '\/nix\/store\/[^']+-source\/flake\.nix' does not exist/i.test(message)
    );
  }

  function appendDebugLog(debugLog, source, message) {
    debugLog.push({
      time: new Date().toISOString(),
      source: source || "libeval-wasm",
      message: String(message || ""),
    });
    if (debugLog.length > 2000) debugLog.splice(0, debugLog.length - 2000);
  }

  function attachDebugLog(response, debugLog) {
    const payload =
      response && typeof response === "object"
        ? response
        : failure("Evaluator did not return a response object.");
    const existing = Array.isArray(payload.debugLog) ? payload.debugLog : [];
    return { ...payload, debugLog: [...debugLog, ...existing] };
  }

  async function preparePersistentStorage(module) {
    const storage = {
      enabled: false,
      backend: "MEMFS",
      mountPoint: "/persist",
      cacheHome: "/persist/cache",
      nixCacheHome: "/persist/cache/nix",
      stateHome: "/persist/state",
      stateDir: "/persist/state/nix/var/nix",
    };
    if (!module.FS) return { ...storage, reason: "Emscripten FS is unavailable" };

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
        if (!message.includes("Mount point is already in use")) {
          storage.reason = `Persistent browser storage unavailable: ${message}`;
        } else {
          module.__nixosRegeditPersistentMounted = true;
        }
      }
    }

    if (module.__nixosRegeditPersistentMounted) {
      try {
        await syncfs(module, true);
        storage.enabled = true;
        storage.backend = "IDBFS";
      } catch (error) {
        const message = String(error && error.message ? error.message : error);
        storage.reason = `Persistent browser storage unavailable: ${message}`;
        module.__nixosRegeditPersistentMounted = false;
      }
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
      module.ENV.NIX_CONFIG = [
        module.ENV.NIX_CONFIG,
        "tarball-ttl = 900",
        "show-trace = true",
        "substituters =",
      ]
        .filter(Boolean)
        .join("\n");
    }

    try {
      await syncfs(module, false);
    } catch (error) {
      const message = String(error && error.message ? error.message : error);
      storage.enabled = false;
      storage.backend = "MEMFS";
      storage.reason = `Persistent browser storage unavailable: ${message}`;
    }
    return storage;
  }

  function workerSource(evaluatorSource) {
    return `
const evaluatorSource = ${JSON.stringify(evaluatorSource)};
const FLAKE_REF_RE = ${FLAKE_REF_RE.toString()};
${nixString.toString()}
${looksLikePayload.toString()}
${failure.toString()}
${looksLikeFlakeRef.toString()}
${splitFlakeSelector.toString()}
${isRemoteFlakeRef.toString()}
${flakeSelectorLookupExpression.toString()}
${flakeSelectorExpression.toString()}
${browserModuleExpression.toString()}
${mkdirTree.toString()}
${syncfs.toString()}
${removeTree.toString()}
${clearNixFetchCache.toString()}
${shouldRetryAfterClearingFetchCache.toString()}
${appendDebugLog.toString()}
${attachDebugLog.toString()}
${preparePersistentStorage.toString()}

let modulePromise = null;
let evaluateRaw = null;
let currentSystemRaw = null;
let storage = null;
let currentDebugLog = [];
let currentDebugRequestId = null;

function emitPhase(phase) {
  if (currentDebugRequestId !== null) {
    self.postMessage({ id: currentDebugRequestId, ok: true, phase });
  }
}

function appendWorkerDebugLog(source, message) {
  const before = currentDebugLog.length;
  appendDebugLog(currentDebugLog, source, message);
  const entry = currentDebugLog[currentDebugLog.length - 1];
  if (currentDebugRequestId !== null && currentDebugLog.length >= before && entry) {
    self.postMessage({ id: currentDebugRequestId, ok: true, debug: true, entry });
  }
}

async function moduleInstance() {
  if (!modulePromise) {
    modulePromise = (async () => {
      (0, eval)(evaluatorSource);
      if (typeof createLibevalWasm !== "function") {
        throw new Error("libeval-wasm did not expose createLibevalWasm.");
      }
      appendWorkerDebugLog("worker", "loading libeval-wasm module");
      const module = await createLibevalWasm({
        print: (line) => appendWorkerDebugLog("stdout", line),
        printErr: (line) => appendWorkerDebugLog("stderr", line),
      });
      storage = await preparePersistentStorage(module);
      evaluateRaw = module.cwrap("libeval_wasm", "string", ["string"]);
      currentSystemRaw = module.cwrap("libeval_wasm_current_system", "string", []);
      appendWorkerDebugLog(
        "worker",
        storage.enabled
          ? "libeval-wasm module ready with persistent browser storage"
          : "libeval-wasm module ready without persistent browser storage" +
              (storage.reason ? " (" + storage.reason + ")" : ""),
      );
      return module;
    })();
  }
  return modulePromise;
}

async function evalNix(expression) {
  const module = await moduleInstance();
  emitPhase("Evaluating");
  appendWorkerDebugLog("libeval-wasm", "evaluating expression");
  const response = JSON.parse(evaluateRaw(expression));
  if (response && response.ok === false) {
    appendWorkerDebugLog("libeval-wasm", "evaluation returned failure");
    if (response.error) appendWorkerDebugLog("libeval-wasm:error", response.error);
  } else {
    appendWorkerDebugLog("libeval-wasm", "evaluation returned result");
  }
  await syncfs(module, false);
  return response;
}

async function evalNixRetryingFetchCacheMismatch(expression) {
  const response = await evalNix(expression);
  if (!response || response.ok !== false || !shouldRetryAfterClearingFetchCache(response)) {
    return response;
  }
  const module = await moduleInstance();
  await clearNixFetchCache(module);
  const retried = await evalNix(expression);
  if (retried && retried.ok === false) return retried;
  return {
    ...retried,
    diagnostics: [
      "Cleared stale browser Nix fetch cache after a cached source mismatch, then retried successfully.",
      ...((retried && retried.diagnostics) || []),
    ],
  };
}

async function currentSystem() {
  await moduleInstance();
  return currentSystemRaw();
}

async function resolve(request) {
  const input = String(request.expression || "").trim();
  const isFlakeRef = looksLikeFlakeRef(input);
  if (!request.allowFetch && isFlakeRef && isRemoteFlakeRef(input)) {
    return failure("Fetch is disabled. Enable Allow fetch to use remote flake references.");
  }
  return {
    ok: true,
    kind: isFlakeRef ? "flake" : "expression",
    identity: input,
    system: request.system || await currentSystem(),
  };
}

async function evaluate(request) {
  currentDebugLog = [];
  appendWorkerDebugLog("worker", "starting evaluation request");
  emitPhase("Evaluating");
  const system = request.system || await currentSystem();
  self.LibevalWasmFetchConfig = {
    ...(request.fetchProxy || {}),
    allowFetch: Boolean(request.allowFetch),
  };
  const input = String(request.expression || "").trim();
  const isFlakeRef = looksLikeFlakeRef(input);
  if (!request.allowFetch && isFlakeRef && isRemoteFlakeRef(input)) {
    return attachDebugLog(
      failure("Fetch is disabled. Enable Allow fetch to use remote flake references."),
      currentDebugLog,
    );
  }
  if (isFlakeRef && request.allowFetch) emitPhase("Fetching");
  const rawResponse = isFlakeRef ? null : await evalNixRetryingFetchCacheMismatch(request.expression);
  if (rawResponse && looksLikePayload(rawResponse)) return attachDebugLog(rawResponse, currentDebugLog);
  const wrappedResponse = await evalNixRetryingFetchCacheMismatch(
    browserModuleExpression(request.expression, system),
  );
  if (wrappedResponse && wrappedResponse.ok === false) {
    return attachDebugLog(wrappedResponse, currentDebugLog);
  }
  if (looksLikePayload(wrappedResponse)) return attachDebugLog(wrappedResponse, currentDebugLog);
  if (rawResponse && rawResponse.ok === false) return attachDebugLog(rawResponse, currentDebugLog);
  return attachDebugLog(
    failure(
      "libeval-wasm ran the Nix expression, but it did not return a NixOS module, module list, nixosModules attrset, or NixOS Regedit payload.",
    ),
    currentDebugLog,
  );
}

self.addEventListener("message", async (event) => {
  const { id, method, request } = event.data || {};
  try {
    let value;
    if (method === "init") {
      await moduleInstance();
      value = { storage };
    } else if (method === "currentSystem") {
      value = await currentSystem();
    } else if (method === "resolve") {
      value = await resolve(request || {});
    } else if (method === "evaluate") {
      currentDebugRequestId = id;
      try {
        value = await evaluate(request || {});
      } finally {
        currentDebugRequestId = null;
      }
    } else {
      throw new Error("Unknown evaluator worker method: " + method);
    }
    self.postMessage({ id, ok: true, value });
  } catch (error) {
    self.postMessage({
      id,
      ok: false,
      error: error && error.message ? error.message : String(error),
    });
  }
});
`;
  }

  async function loadWorkerEvaluator(evaluatorSource) {
    if (typeof Worker !== "function" || typeof Blob !== "function" || typeof URL !== "function") {
      return false;
    }

    const workerScript = new Blob([workerSource(evaluatorSource)], { type: "text/javascript" });
    const url = URL.createObjectURL(workerScript);
    let worker = null;
    let ready = null;
    let nextId = 0;
    const pending = new Map();

    const attachWorkerHandlers = (activeWorker) => {
      activeWorker.addEventListener("message", (event) => {
        const { id, ok, value, error, debug, entry, phase } = event.data || {};
        const deferred = pending.get(id);
        if (!deferred) return;
        if (debug) {
          if (typeof deferred.onDebugLog === "function") deferred.onDebugLog(entry);
          return;
        }
        if (phase) {
          if (typeof deferred.onPhase === "function") deferred.onPhase(phase);
          return;
        }
        pending.delete(id);
        if (ok) deferred.resolve(value);
        else deferred.reject(new Error(error || "Evaluator worker failed."));
      });

      activeWorker.addEventListener("error", failPending);
      activeWorker.addEventListener("messageerror", failPending);
    };

    const failPending = (error) => {
      const detail = error && error.message ? error.message : String(error || "cancelled");
      for (const deferred of pending.values()) deferred.reject(new Error(detail));
      pending.clear();
    };

    const call = (method, request, onDebugLog, onPhase) =>
      new Promise((resolve, reject) => {
        const id = ++nextId;
        pending.set(id, { resolve, reject, onDebugLog, onPhase });
        worker.postMessage({ id, method, request });
      });

    const spawnWorker = () => {
      worker = new Worker(url, { name: "nixos-regedit-libeval-wasm" });
      attachWorkerHandlers(worker);
      ready = call("init");
      return ready;
    };

    const initialized = await spawnWorker();
    const api = {
      storage: initialized.storage,
      currentSystem: async () => {
        await ready;
        return call("currentSystem");
      },
      resolve: async (request) => {
        const { signal, onDebugLog, onPhase, ...serializableRequest } = request || {};
        await ready;
        return call("resolve", serializableRequest, onDebugLog, onPhase);
      },
      evaluate: async (request) => {
        const { signal, onDebugLog, onPhase, ...serializableRequest } = request || {};
        await ready;
        return call("evaluate", serializableRequest, onDebugLog, onPhase);
      },
      cancel: () => {
        if (worker) worker.terminate();
        failPending(new Error("Evaluation cancelled."));
        ready = spawnWorker().then((nextInitialized) => {
          api.storage = nextInitialized.storage;
          return nextInitialized;
        });
      },
    };
    window.NixOSRegeditEvaluator = api;
    window.dispatchEvent(new CustomEvent("nixos-regedit-evaluator-ready"));
    return true;
  }

  async function loadEvaluator() {
    if (window.NixOSRegeditStandaloneEvaluatorSource) {
      try {
        const loaded = await loadWorkerEvaluator(window.NixOSRegeditStandaloneEvaluatorSource);
        if (loaded) return true;
      } catch (error) {
        window.NixOSRegeditEvaluatorLoadError =
          error && error.message ? error.message : String(error);
      }
      if (typeof window.createLibevalWasm !== "function") {
        (0, eval)(window.NixOSRegeditStandaloneEvaluatorSource);
      }
    }

    const createEvaluator = window.createLibevalWasm;
    if (typeof createEvaluator !== "function") return false;
    let currentDebugLog = [];
    let currentDebugSink = null;
    let cancelled = false;
    let currentDebugPhase = null;
    const emitLocalPhase = (phase) => {
      if (typeof currentDebugPhase === "function") currentDebugPhase(phase);
    };
    const appendLocalDebugLog = (source, message) => {
      const before = currentDebugLog.length;
      appendDebugLog(currentDebugLog, source, message);
      const entry = currentDebugLog[currentDebugLog.length - 1];
      if (currentDebugSink && currentDebugLog.length >= before && entry) currentDebugSink(entry);
    };
    appendLocalDebugLog("loader", "loading libeval-wasm module");
    const module = await createEvaluator({
      print: (line) => appendLocalDebugLog("stdout", line),
      printErr: (line) => appendLocalDebugLog("stderr", line),
    });
    const storage = await preparePersistentStorage(module);
    const evaluateRaw = module.cwrap("libeval_wasm", "string", ["string"]);
    const currentSystemRaw = module.cwrap("libeval_wasm_current_system", "string", []);
    appendLocalDebugLog(
      "loader",
      storage.enabled
        ? "libeval-wasm module ready with persistent browser storage"
        : "libeval-wasm module ready without persistent browser storage" +
            (storage.reason ? " (" + storage.reason + ")" : ""),
    );
    const evalNix = async (expression) => {
      appendLocalDebugLog("libeval-wasm", "evaluating expression");
      const response = JSON.parse(evaluateRaw(expression));
      if (response && response.ok === false) {
        appendLocalDebugLog("libeval-wasm", "evaluation returned failure");
        if (response.error) appendLocalDebugLog("libeval-wasm:error", response.error);
      } else {
        appendLocalDebugLog("libeval-wasm", "evaluation returned result");
      }
      await syncfs(module, false);
      return response;
    };
    const evalNixRetryingFetchCacheMismatch = async (expression) => {
      const response = await evalNix(expression);
      if (!response || response.ok !== false || !shouldRetryAfterClearingFetchCache(response)) {
        return response;
      }
      await clearNixFetchCache(module);
      const retried = await evalNix(expression);
      if (retried && retried.ok === false) return retried;
      return {
        ...retried,
        diagnostics: [
          "Cleared stale browser Nix fetch cache after a cached source mismatch, then retried successfully.",
          ...((retried && retried.diagnostics) || []),
        ],
      };
    };
    window.NixOSRegeditEvaluator = {
      storage,
      currentSystem: async () => currentSystemRaw(),
      resolve: async (request) => {
        const { signal, onDebugLog, onPhase, ...serializableRequest } = request || {};
        const input = String(serializableRequest.expression || "").trim();
        const isFlakeRef = looksLikeFlakeRef(input);
        if (!serializableRequest.allowFetch && isFlakeRef && isRemoteFlakeRef(input)) {
          return failure("Fetch is disabled. Enable Allow fetch to use remote flake references.");
        }
        return {
          ok: true,
          kind: isFlakeRef ? "flake" : "expression",
          identity: input,
          system: serializableRequest.system || currentSystemRaw(),
        };
      },
      evaluate: async (request) => {
        const { signal, onDebugLog, onPhase, ...serializableRequest } = request || {};
        currentDebugLog = [];
        currentDebugSink = typeof onDebugLog === "function" ? onDebugLog : null;
        currentDebugPhase = typeof onPhase === "function" ? onPhase : null;
        cancelled = false;
        try {
          appendLocalDebugLog("loader", "starting evaluation request");
          emitLocalPhase("Evaluating");
          const system = serializableRequest.system || currentSystemRaw();
          window.LibevalWasmFetchConfig = {
            ...(serializableRequest.fetchProxy || {}),
            allowFetch: Boolean(serializableRequest.allowFetch),
          };
          const input = String(serializableRequest.expression || "").trim();
          const isFlakeRef = looksLikeFlakeRef(input);
          if (!serializableRequest.allowFetch && isFlakeRef && isRemoteFlakeRef(input)) {
            return attachDebugLog(
              failure("Fetch is disabled. Enable Allow fetch to use remote flake references."),
              currentDebugLog,
            );
          }
          if (isFlakeRef && serializableRequest.allowFetch) emitLocalPhase("Fetching");
          const rawResponse = isFlakeRef
            ? null
            : await evalNixRetryingFetchCacheMismatch(serializableRequest.expression);
          if (cancelled) throw new Error("Evaluation cancelled.");
          if (rawResponse && looksLikePayload(rawResponse)) {
            return attachDebugLog(rawResponse, currentDebugLog);
          }
          const wrappedResponse = await evalNixRetryingFetchCacheMismatch(
            browserModuleExpression(serializableRequest.expression, system),
          );
          if (cancelled) throw new Error("Evaluation cancelled.");
          if (wrappedResponse && wrappedResponse.ok === false) {
            return attachDebugLog(wrappedResponse, currentDebugLog);
          }
          if (looksLikePayload(wrappedResponse)) {
            return attachDebugLog(wrappedResponse, currentDebugLog);
          }
          if (rawResponse && rawResponse.ok === false) {
            return attachDebugLog(rawResponse, currentDebugLog);
          }
          return attachDebugLog(
            failure(
              "libeval-wasm ran the Nix expression, but it did not return a NixOS module, module list, nixosModules attrset, or NixOS Regedit payload.",
            ),
            currentDebugLog,
          );
        } finally {
          currentDebugSink = null;
          currentDebugPhase = null;
        }
      },
      cancel: () => {
        cancelled = true;
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
