"""Nix evaluator for NixOS-module-shaped inputs."""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote

Runner = Callable[..., subprocess.CompletedProcess[str]]
DebugSink = Callable[[dict[str, str]], None]


class EvaluationFailure(Exception):
    def __init__(self, error: str, attempts: list[dict[str, Any]]):
        super().__init__(error)
        self.error = error
        self.attempts = attempts


@dataclass(frozen=True)
class EvaluationRequest:
    expression: str
    allow_fetch: bool = False
    system: str | None = None


FLAKE_REF_RE = re.compile(r"^[A-Za-z0-9+._:/?=@%~-]+(?:#[A-Za-z0-9+._/?=@%~-]+)?$")
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
CURRENT_SYSTEM_EXPR = "builtins.currentSystem"
SELF_FLAKE_ENV_VAR = "NIXOS_REGEDIT_FLAKE_REF"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FLAKE_SELECTOR = "nixosModules.default"
MISSING_DEFAULT_SELECTOR_MARKER = "__NIXOS_REGEDIT_MISSING_DEFAULT_SELECTOR__"
MISSING_NIXOS_SYSTEM_MARKER = "__NIXOS_REGEDIT_MISSING_NIXOS_SYSTEM__"
MISSING_MODULE_LIST_MARKER = "__NIXOS_REGEDIT_MISSING_MODULE_LIST__"
DEBUG_LOG_LIMIT = 2000


def self_flake_ref() -> str:
    return os.environ.get(SELF_FLAKE_ENV_VAR, f"path:{REPO_ROOT}")


def current_system(*, runner: Runner | None = None, cwd: str | None = None) -> str:
    runner = runner or subprocess.run
    completed = runner(
        ["nix", "eval", "--raw", "--impure", "--expr", CURRENT_SYSTEM_EXPR],
        cwd=cwd or os.getcwd(),
        text=True,
        capture_output=True,
        timeout=15,
    )
    if completed.returncode != 0:
        return "builtins.currentSystem"
    return completed.stdout.strip() or "builtins.currentSystem"


def parse_request(payload: dict[str, Any]) -> EvaluationRequest:
    expression = payload.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression is required")
    allow_fetch = payload.get("allowFetch", False)
    if not isinstance(allow_fetch, bool):
        raise ValueError("allowFetch must be a boolean")
    system = payload.get("system")
    if system is None or system == "":
        system = None
    elif not isinstance(system, str):
        raise ValueError("system must be a string")
    else:
        system = system.strip() or None
    return EvaluationRequest(expression=expression.strip(), allow_fetch=allow_fetch, system=system)


def looks_like_flake_ref(value: str) -> bool:
    stripped = value.strip()
    if not stripped or "\n" in stripped:
        return False
    if stripped.startswith(("{", "[", "(", "let ", "with ", "rec ")):
        return False
    return bool(FLAKE_REF_RE.match(stripped))


def build_command(nix_expr: str, allow_fetch: bool) -> list[str]:
    command = [
        "nix",
        "--extra-experimental-features",
        "nix-command flakes",
        "eval",
        "--debug",
        "--json",
        "--impure",
    ]
    if not allow_fetch:
        command.append("--offline")
    command.extend(["--expr", nix_expr])
    return command


def _debug_timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def debug_entries_from_attempts(attempts: list[dict[str, Any]]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for attempt in attempts:
        mode = str(attempt.get("mode") or "nix")
        for stream in ("stderr", "stdout"):
            text = attempt.get(stream)
            if not isinstance(text, str) or not text:
                continue
            for line in text.splitlines():
                if line:
                    entries.append(
                        {
                            "time": _debug_timestamp(),
                            "source": f"{mode}:{stream}",
                            "message": line,
                        }
                    )
    if len(entries) > DEBUG_LOG_LIMIT:
        return entries[-DEBUG_LOG_LIMIT:]
    return entries


def make_debug_entry(source: str, message: str) -> dict[str, str]:
    return {
        "time": _debug_timestamp(),
        "source": source,
        "message": message,
    }


def run_eval(
    nix_expr: str, *, allow_fetch: bool, cwd: str, timeout: int
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        build_command(nix_expr, allow_fetch),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def run_command_streaming_debug(
    command: list[str],
    *,
    cwd: str,
    timeout: int,
    debug_sink: DebugSink | None,
    debug_source: str,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout_parts: list[str] = []
    stderr_lines: list[str] = []

    def read_stdout() -> None:
        assert process.stdout is not None
        while True:
            chunk = process.stdout.read(65536)
            if chunk == "":
                break
            stdout_parts.append(chunk)

    def read_stderr() -> None:
        assert process.stderr is not None
        for line in process.stderr:
            stripped = line.rstrip("\n")
            stderr_lines.append(stripped)
            if debug_sink and stripped:
                debug_sink(make_debug_entry(f"{debug_source}:stderr", stripped))

    stdout_thread = threading.Thread(target=read_stdout, daemon=True)
    stderr_thread = threading.Thread(target=read_stderr, daemon=True)
    stdout_thread.start()
    stderr_thread.start()
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait()
        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
        raise
    stdout_thread.join(timeout=5)
    stderr_thread.join(timeout=5)
    if process.stdout:
        process.stdout.close()
    if process.stderr:
        process.stderr.close()
    return subprocess.CompletedProcess(
        command,
        returncode,
        "".join(stdout_parts),
        "\n".join(stderr_lines),
    )


def build_flake_metadata_command(ref: str, allow_fetch: bool) -> list[str]:
    command = [
        "nix",
        "--extra-experimental-features",
        "nix-command flakes",
    ]
    if not allow_fetch:
        command.append("--offline")
    command.extend(["flake", "metadata", "--json", ref])
    return command


def split_flake_selector(ref: str) -> tuple[str, str]:
    base, separator, selector = ref.strip().partition("#")
    return base, selector if separator and selector else DEFAULT_FLAKE_SELECTOR


def has_explicit_flake_selector(ref: str) -> bool:
    return "#" in ref.strip()


def nix_string_list(values: list[str]) -> str:
    return "[ " + " ".join(json.dumps(value) for value in values) + " ]"


def nix_attrpath(components: list[str]) -> str:
    return (
        "(builtins.foldl' (value: name: builtins.getAttr name value) flake "
        f"{nix_string_list(components)})"
    )


def nix_attrpath_or_throw(components: list[str], marker: str) -> str:
    path = nix_string_list(components)
    return f"""
    let
      selected = builtins.foldl' (
        state: name:
          if state.found && builtins.isAttrs state.value && builtins.hasAttr name state.value
          then {{ found = true; value = builtins.getAttr name state.value; }}
          else {{ found = false; value = null; }}
      ) {{ found = true; value = flake; }} {path};
    in
      if selected.found
      then selected.value
      else throw {json.dumps(marker)}
    """


def normalize_flake_ref(ref: str, cwd: str) -> str:
    base, selector = split_flake_selector(ref)
    if SCHEME_RE.match(base):
        return base if selector == DEFAULT_FLAKE_SELECTOR else f"{base}#{selector}"
    candidate = base if os.path.isabs(base) else os.path.join(cwd, base)
    if os.path.exists(candidate):
        normalized = "path:" + os.path.abspath(candidate)
        return normalized if selector == DEFAULT_FLAKE_SELECTOR else f"{normalized}#{selector}"
    return ref


def is_remote_flake_ref(ref: str) -> bool:
    base, _selector = split_flake_selector(ref)
    return SCHEME_RE.match(base) is not None and not base.startswith("path:")


def resolve_flake_metadata(
    ref: str,
    allow_fetch: bool,
    *,
    runner: Runner,
    cwd: str,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_ref = normalize_flake_ref(ref, cwd)
    if not allow_fetch and is_remote_flake_ref(normalized_ref):
        raise EvaluationFailure(
            "Fetch is disabled. Enable Allow fetch to use remote flake references.",
            [
                {
                    "mode": "flake-metadata",
                    "command": build_flake_metadata_command(normalized_ref, allow_fetch),
                    "returncode": None,
                    "stderr": ("Refusing to resolve a remote flake while fetch is disabled."),
                }
            ],
        )
    command = build_flake_metadata_command(normalized_ref, allow_fetch)
    completed = runner(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    attempt = {
        "mode": "flake-metadata",
        "command": command,
        "returncode": completed.returncode,
        "stderr": completed.stderr[-6000:],
    }
    if completed.returncode != 0:
        raise EvaluationFailure("Could not resolve flake reference.", [attempt])

    try:
        metadata = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        attempt["stdout"] = completed.stdout[-2000:]
        attempt["jsonError"] = str(exc)
        raise EvaluationFailure("Nix returned invalid flake metadata JSON.", [attempt]) from exc
    return metadata, attempt


def flake_metadata_identity(
    metadata: dict[str, Any], selector: str = DEFAULT_FLAKE_SELECTOR
) -> str:
    identity = flake_metadata_ref(metadata)
    return f"{identity}#{selector}"


def flake_metadata_ref(metadata: dict[str, Any]) -> str:
    url = metadata.get("url")
    if url:
        return unquote(url)
    return json.dumps(metadata.get("locked", metadata), sort_keys=True)


def resolve_payload(
    payload: dict[str, Any],
    *,
    runner: Runner | None = None,
    cwd: str | None = None,
    timeout: int = 60,
) -> dict[str, Any]:
    request = parse_request(payload)
    runner = runner or subprocess.run
    cwd = cwd or os.getcwd()
    system = request.system or current_system(runner=runner, cwd=cwd)

    if not looks_like_flake_ref(request.expression):
        return {
            "ok": True,
            "kind": "expression",
            "identity": request.expression,
            "system": system,
            "attempts": [],
        }

    base_ref, selector = split_flake_selector(request.expression)
    metadata, attempt = resolve_flake_metadata(
        base_ref,
        request.allow_fetch,
        runner=runner,
        cwd=cwd,
        timeout=timeout,
    )
    identity = flake_metadata_identity(metadata, selector)
    return {
        "ok": True,
        "kind": "flake",
        "identity": identity,
        "input": request.expression,
        "system": system,
        "attempts": [attempt],
    }


def flake_ref_expr(
    ref: str, system: str | None, *, missing_selector_marker: str | None = None
) -> str:
    base_ref, selector = split_flake_selector(ref)
    selector_components = [part for part in selector.split(".") if part]
    components = selector_components or DEFAULT_FLAKE_SELECTOR.split(".")
    selected_path = ".".join(components)
    selector_expr = (
        nix_attrpath_or_throw(components, missing_selector_marker)
        if missing_selector_marker
        else nix_attrpath(components)
    )
    return _wrap_input(
        selector_expr,
        "flake-nixosModules",
        system=system,
        prelude=f"""
  flake = builtins.getFlake {json.dumps(base_ref)};
  flakeModulesPath = flake.outPath + "/nixos/modules";
  flakeModuleList = flakeModulesPath + "/module-list.nix";
  flakePkgs =
    if flake ? legacyPackages && builtins.hasAttr selectedSystem flake.legacyPackages
    then builtins.getAttr selectedSystem flake.legacyPackages
    else fallbackPkgs;
  flakeNixosSystemLib =
    if flake ? lib && flake.lib ? nixosSystem
    then flake.lib
    else if flake ? inputs
      && flake.inputs ? nixpkgs
      && flake.inputs.nixpkgs ? lib
      && flake.inputs.nixpkgs.lib ? nixosSystem
    then flake.inputs.nixpkgs.lib
    else null;
""",
        modules_path_expr=(
            'if builtins.pathExists flakeModulesPath then flakeModulesPath else "/nixos/modules"'
        ),
        pkgs_expr="flakePkgs",
        module_source_expr=json.dumps(f"flake attribute .#{selected_path}"),
        nixos_system_options_expr=(
            "if flakeNixosSystemLib != null "
            "then (flakeNixosSystemLib.nixosSystem { system = selectedSystem; "
            "modules = modules; }).options "
            "else null"
        ),
    )


def flake_module_list_expr(ref: str, system: str | None) -> str:
    base_ref, _selector = split_flake_selector(ref)
    return _wrap_input(
        "[ ]",
        "flake-module-list",
        system=system,
        prelude=f"""
  flake = builtins.getFlake {json.dumps(base_ref)};
  flakeModulesPath = flake.outPath + "/nixos/modules";
  flakeModuleList = flakeModulesPath + "/module-list.nix";
  flakePkgs =
    if flake ? legacyPackages && builtins.hasAttr selectedSystem flake.legacyPackages
    then builtins.getAttr selectedSystem flake.legacyPackages
    else fallbackPkgs;
  flakeNixosSystemLib =
    if flake ? lib && flake.lib ? nixosSystem
    then flake.lib
    else if flake ? inputs
      && flake.inputs ? nixpkgs
      && flake.inputs.nixpkgs ? lib
      && flake.inputs.nixpkgs.lib ? nixosSystem
    then flake.inputs.nixpkgs.lib
    else null;
""",
        base_modules_expr=f"""
          if builtins.pathExists flakeModuleList
          then import flakeModuleList
          else throw {json.dumps(MISSING_MODULE_LIST_MARKER)}
        """,
        modules_path_expr=(
            'if builtins.pathExists flakeModulesPath then flakeModulesPath else "/nixos/modules"'
        ),
        pkgs_expr="flakePkgs",
        module_source_expr=json.dumps("nixos/modules/module-list.nix"),
        nixos_system_options_expr=(
            "if flakeNixosSystemLib != null "
            "then (flakeNixosSystemLib.nixosSystem { system = selectedSystem; "
            "modules = modules; }).options "
            "else null"
        ),
    )


def flake_nixos_system_expr(ref: str, system: str | None) -> str:
    base_ref, _selector = split_flake_selector(ref)
    mode_json = json.dumps("flake-nixosSystem")
    system_expr = CURRENT_SYSTEM_EXPR if system is None else json.dumps(system)
    self_ref = json.dumps(self_flake_ref())
    marker = json.dumps(MISSING_NIXOS_SYSTEM_MARKER)
    return f"""
let
  flake = builtins.getFlake {json.dumps(base_ref)};
  support = builtins.getFlake {self_ref};
  selectedSystem = {system_expr};
  nixosOptionsDoc = support.lib.nixosOptionsDoc;
  safeDocValue = fallback: value:
    let attempted = builtins.tryEval (builtins.deepSeq value value);
    in if attempted.success then attempted.value else fallback;
  safeDocField = option: name: fallback:
    if builtins.hasAttr name option
    then safeDocValue fallback (builtins.getAttr name option)
    else fallback;
  safeDocOption = option: option // {{
    declarations = safeDocField option "declarations" [];
    default = safeDocField option "default" (safeDocField option "defaultText" null);
    description = safeDocField option "description" "";
    example = safeDocField option "example" (safeDocField option "exampleText" null);
    readOnly = safeDocField option "readOnly" false;
    relatedPackages = safeDocField option "relatedPackages" [];
    type = safeDocField option "type" "unspecified";
  }};
  lib =
    if flake ? lib && flake.lib ? nixosSystem
    then flake.lib
    else if flake ? inputs
      && flake.inputs ? nixpkgs
      && flake.inputs.nixpkgs ? lib
      && flake.inputs.nixpkgs.lib ? nixosSystem
    then flake.inputs.nixpkgs.lib
    else throw {marker};
  eval = lib.nixosSystem {{
    system = selectedSystem;
    modules = [ ];
  }};
  docs = nixosOptionsDoc {{
    inherit lib;
    inherit (eval) options;
    transformOptions = safeDocOption;
    warningsAreErrors = false;
  }};
  options = docs.optionsNix;
in {{
  ok = true;
  mode = {mode_json};
  system = selectedSystem;
  moduleNames = [ "nixosSystem" ];
  moduleCount = 0;
  moduleSource =
    if flake ? lib && flake.lib ? nixosSystem
    then "flake.lib.nixosSystem"
    else "flake.inputs.nixpkgs.lib.nixosSystem";
  optionCount = builtins.length (builtins.attrNames options);
  inherit options;
  diagnostics = [];
}}
"""


def module_collection_expr(expression: str, system: str | None) -> str:
    return _wrap_input(
        f"({expression})",
        "expression-nixosModules",
        system=system,
    )


def _wrap_input(
    input_expr: str,
    mode: str,
    *,
    system: str | None,
    prelude: str = "",
    base_modules_expr: str = "[ ]",
    modules_path_expr: str = '"/nixos/modules"',
    pkgs_expr: str = "fallbackPkgs",
    module_source_expr: str = json.dumps("input expression"),
    nixos_system_options_expr: str = "null",
) -> str:
    mode_json = json.dumps(mode)
    system_expr = CURRENT_SYSTEM_EXPR if system is None else json.dumps(system)
    self_ref = json.dumps(self_flake_ref())
    return f"""
let
  {prelude}
  support = builtins.getFlake {self_ref};
  selectedSystem = {system_expr};
  lib = support.lib.nixpkgsLib;
  nixosOptionsDoc = support.lib.nixosOptionsDoc;
  safeDocValue = fallback: value:
    let attempted = builtins.tryEval (builtins.deepSeq value value);
    in if attempted.success then attempted.value else fallback;
  safeDocField = option: name: fallback:
    if builtins.hasAttr name option
    then safeDocValue fallback (builtins.getAttr name option)
    else fallback;
  safeDocOption = option: option // {{
    declarations = safeDocField option "declarations" [];
    default = safeDocField option "default" (safeDocField option "defaultText" null);
    description = safeDocField option "description" "";
    example = safeDocField option "example" (safeDocField option "exampleText" null);
    readOnly = safeDocField option "readOnly" false;
    relatedPackages = safeDocField option "relatedPackages" [];
    type = safeDocField option "type" "unspecified";
  }};
  modulesPath = {modules_path_expr};
  fallbackPkgs = {{
    inherit lib;
    stdenv = {{
      hostPlatform = {{
        system = selectedSystem;
      }};
    }};
  }};
  pkgs = {pkgs_expr};

  isModule = value:
    builtins.isFunction value
    || (
      builtins.isAttrs value
      && (
        value ? imports
        || value ? options
        || value ? config
        || value ? _module
        || value ? disabledModules
        || value ? freeformType
      )
    );

  moduleNames = value:
    if builtins.isAttrs value && !(isModule value)
    then builtins.attrNames value
    else [ "default" ];

  moduleValues = value:
    if builtins.isList value then value
    else if isModule value then [ value ]
    else if builtins.isAttrs value then builtins.attrValues value
    else throw ''
      Expected a module, a list of modules, or an attrset shaped like flake.nixosModules.
    '';

  render = value:
    let
      modules = ({base_modules_expr}) ++ moduleValues value;
      nixosSystemOptions = {nixos_system_options_expr};
      rawOptions =
        if nixosSystemOptions != null
        then nixosSystemOptions
        else (lib.evalModules {{
          inherit modules;
          specialArgs = {{
            inherit lib pkgs modulesPath;
          }};
        }}).options;
      docs = nixosOptionsDoc {{
        inherit lib;
        options = rawOptions;
        transformOptions = safeDocOption;
        warningsAreErrors = false;
      }};
      options = docs.optionsNix;
    in {{
      ok = true;
      mode = {mode_json};
      system = selectedSystem;
      moduleSource = {module_source_expr};
      moduleNames = moduleNames value;
      moduleCount = builtins.length modules;
      optionCount = builtins.length (builtins.attrNames options);
      inherit options;
      diagnostics = [];
    }};
in
  render ({input_expr})
"""


def evaluate(
    request: EvaluationRequest,
    *,
    runner: Runner | None = None,
    cwd: str | None = None,
    timeout: int = 120,
    debug_sink: DebugSink | None = None,
) -> dict[str, Any]:
    runner_provided = runner is not None
    runner = runner or subprocess.run
    cwd = cwd or os.getcwd()
    candidates: list[tuple[str, str]] = []
    attempts: list[dict[str, Any]] = []

    def run_candidate(
        mode: str, nix_expr: str
    ) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
        command = build_command(nix_expr, request.allow_fetch)
        if runner_provided:
            completed = runner(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        else:
            completed = run_command_streaming_debug(
                command,
                cwd=cwd,
                timeout=timeout,
                debug_sink=debug_sink,
                debug_source=mode,
            )
        attempt = {
            "mode": mode,
            "command": command[:7] + ["..."],
            "returncode": completed.returncode,
            "stderr": completed.stderr[-6000:],
        }
        return attempt, completed

    def result_from_completed(
        mode: str, attempt: dict[str, Any], completed: subprocess.CompletedProcess[str]
    ) -> dict[str, Any] | None:
        if completed.returncode != 0:
            return None
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            attempt["stdout"] = completed.stdout[-2000:]
            attempt["jsonError"] = str(exc)
            return None
        result.setdefault("mode", mode)
        result.setdefault("diagnostics", [])
        result["diagnostics"].append(
            {
                "level": "info",
                "message": f"Evaluated {result.get('moduleCount', 0)} module(s) in {mode}.",
            }
        )
        result["attempts"] = attempts
        result["debugLog"] = debug_entries_from_attempts(attempts)
        return result

    if looks_like_flake_ref(request.expression):
        base_ref, selector = split_flake_selector(request.expression)
        try:
            metadata, attempt = resolve_flake_metadata(
                base_ref,
                request.allow_fetch,
                runner=runner,
                cwd=cwd,
                timeout=timeout,
            )
        except EvaluationFailure as exc:
            attempts.extend(exc.attempts)
        else:
            attempts.append(attempt)
            resolved_ref = flake_metadata_ref(metadata)
            if has_explicit_flake_selector(request.expression):
                mode = "flake-nixosModules"
                nix_expr = flake_ref_expr(f"{resolved_ref}#{selector}", request.system)
                attempt, completed = run_candidate(mode, nix_expr)
                attempts.append(attempt)
                result = result_from_completed(mode, attempt, completed)
                if result is not None:
                    return result
                raise EvaluationFailure(
                    "Could not evaluate the selected flake output as NixOS modules.",
                    attempts,
                )

            mode = "flake-nixosModules"
            nix_expr = flake_ref_expr(
                f"{resolved_ref}#{DEFAULT_FLAKE_SELECTOR}",
                request.system,
                missing_selector_marker=MISSING_DEFAULT_SELECTOR_MARKER,
            )
            attempt, completed = run_candidate(mode, nix_expr)
            attempts.append(attempt)
            result = result_from_completed(mode, attempt, completed)
            if result is not None:
                return result
            if MISSING_DEFAULT_SELECTOR_MARKER not in attempt["stderr"]:
                raise EvaluationFailure(
                    "Could not evaluate .#nixosModules.default as NixOS modules.",
                    attempts,
                )

            mode = "flake-nixosSystem"
            nix_expr = flake_nixos_system_expr(resolved_ref, request.system)
            attempt, completed = run_candidate(mode, nix_expr)
            attempts.append(attempt)
            result = result_from_completed(mode, attempt, completed)
            if result is not None:
                return result
            if MISSING_NIXOS_SYSTEM_MARKER not in attempt["stderr"]:
                raise EvaluationFailure(
                    "Flake does not expose .#nixosModules.default, and flake.lib.nixosSystem "
                    "could not evaluate its default NixOS modules.",
                    attempts,
                )

            mode = "flake-module-list"
            nix_expr = flake_module_list_expr(resolved_ref, request.system)
            attempt, completed = run_candidate(mode, nix_expr)
            attempts.append(attempt)
            result = result_from_completed(mode, attempt, completed)
            if result is not None:
                return result
            if MISSING_MODULE_LIST_MARKER in attempt["stderr"]:
                raise EvaluationFailure(
                    "Flake does not expose .#nixosModules.default, flake.lib.nixosSystem, "
                    "or nixos/modules/module-list.nix.",
                    attempts,
                )
            raise EvaluationFailure(
                "Flake .#nixosModules.default and flake.lib.nixosSystem are missing, and "
                "nixos/modules/module-list.nix could not be evaluated as NixOS modules.",
                attempts,
            )
    candidates.append(
        ("expression-nixosModules", module_collection_expr(request.expression, request.system))
    )

    for mode, nix_expr in candidates:
        attempt, completed = run_candidate(mode, nix_expr)
        attempts.append(attempt)
        result = result_from_completed(mode, attempt, completed)
        if result is not None:
            return result

    message = (
        "Could not evaluate expression as a flake output containing NixOS modules or a "
        "nixosModules-shaped expression. Bare flake URIs default to #nixosModules.default."
    )
    raise EvaluationFailure(message, attempts)


def evaluate_payload(
    payload: dict[str, Any],
    *,
    runner: Runner | None = None,
    cwd: str | None = None,
    timeout: int = 120,
    debug_sink: DebugSink | None = None,
) -> dict[str, Any]:
    request = parse_request(payload)
    return evaluate(request, runner=runner, cwd=cwd, timeout=timeout, debug_sink=debug_sink)
