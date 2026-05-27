"""Nix evaluator for NixOS-module-shaped inputs."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from urllib.parse import unquote
from dataclasses import dataclass
from typing import Any, Callable


Runner = Callable[..., subprocess.CompletedProcess[str]]


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
HELPER_ENV_VAR = "NIXOS_REGEDIT_EVAL_HELPER"
DISABLE_HELPER_ENV_VAR = "NIXOS_REGEDIT_DISABLE_EVAL_HELPER"


def current_system(*, runner: Runner | None = None, cwd: str | None = None) -> str:
    if runner is None:
        completed = run_eval(CURRENT_SYSTEM_EXPR, allow_fetch=False, cwd=cwd or os.getcwd(), timeout=15)
        if completed.returncode == 0:
            try:
                value = json.loads(completed.stdout)
            except json.JSONDecodeError:
                value = completed.stdout.strip()
            if isinstance(value, str) and value:
                return value
        runner = subprocess.run
    else:
        runner = runner
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
        "--json",
        "--impure",
    ]
    if not allow_fetch:
        command.append("--offline")
    command.extend(["--expr", nix_expr])
    return command


def eval_helper_path() -> str | None:
    if os.environ.get(DISABLE_HELPER_ENV_VAR):
        return None
    configured = os.environ.get(HELPER_ENV_VAR)
    if configured:
        return configured
    return shutil.which("nixos-regedit-eval-helper")


def build_helper_command(allow_fetch: bool, cwd: str) -> list[str]:
    helper = eval_helper_path()
    if helper is None:
        raise FileNotFoundError("nixos-regedit-eval-helper was not found")
    command = [helper, "--cwd", cwd]
    if not allow_fetch:
        command.append("--offline")
    return command


def run_eval(nix_expr: str, *, allow_fetch: bool, cwd: str, timeout: int) -> subprocess.CompletedProcess[str]:
    helper = eval_helper_path()
    if helper:
        return subprocess.run(
            build_helper_command(allow_fetch, cwd),
            input=nix_expr,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    return subprocess.run(
        build_command(nix_expr, allow_fetch),
        cwd=cwd,
        text=True,
        capture_output=True,
        timeout=timeout,
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


def normalize_flake_ref(ref: str, cwd: str) -> str:
    if SCHEME_RE.match(ref):
        return ref
    candidate = ref if os.path.isabs(ref) else os.path.join(cwd, ref)
    if os.path.exists(candidate):
        return "path:" + os.path.abspath(candidate)
    return ref


def is_remote_unpinned_flake_ref(ref: str) -> bool:
    return SCHEME_RE.match(ref) is not None and not ref.startswith("path:") and "narHash=" not in ref


def resolve_flake_metadata(
    ref: str,
    allow_fetch: bool,
    *,
    runner: Runner,
    cwd: str,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_ref = normalize_flake_ref(ref, cwd)
    if not allow_fetch and is_remote_unpinned_flake_ref(normalized_ref):
        raise EvaluationFailure(
            "Fetch is disabled. Enable Allow fetch or provide a pinned flake URI with narHash.",
            [
                {
                    "mode": "flake-metadata",
                    "command": build_flake_metadata_command(normalized_ref, allow_fetch),
                    "returncode": None,
                    "stderr": "Refusing to resolve an unlocked remote flake while fetch is disabled.",
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


def flake_metadata_identity(metadata: dict[str, Any]) -> str:
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

    metadata, attempt = resolve_flake_metadata(
        request.expression,
        request.allow_fetch,
        runner=runner,
        cwd=cwd,
        timeout=timeout,
    )
    identity = flake_metadata_identity(metadata)
    return {
        "ok": True,
        "kind": "flake",
        "identity": identity,
        "input": request.expression,
        "system": system,
        "attempts": [attempt],
    }


def flake_ref_expr(ref: str, system: str | None) -> str:
    return _wrap_input(
        "flake.nixosModules",
        'if builtins.pathExists (flake.outPath + "/nixos/lib/eval-config.nix") then flake.outPath else <nixpkgs>',
        "flake-nixosModules",
        evaluator="nixos",
        system=system,
        prelude=f"flake = builtins.getFlake {json.dumps(ref)};",
    )


def module_collection_expr(expression: str, system: str | None) -> str:
    return _wrap_input(
        f"({expression})",
        "<nixpkgs>",
        "expression-nixosModules",
        evaluator="plain",
        system=system,
    )


def _wrap_input(
    input_expr: str,
    source_expr: str,
    mode: str,
    *,
    evaluator: str,
    system: str | None,
    prelude: str = "",
) -> str:
    mode_json = json.dumps(mode)
    system_expr = CURRENT_SYSTEM_EXPR if system is None else json.dumps(system)
    if evaluator == "nixos":
        eval_expr = """
      import (source + "/nixos/lib/eval-config.nix") {
        inherit modules pkgs;
        system = null;
      }
"""
    elif evaluator == "plain":
        eval_expr = """
      lib.evalModules {
        inherit modules;
        specialArgs = {
          inherit lib pkgs modulesPath;
        };
      }
"""
    else:
        raise ValueError(f"unknown evaluator {evaluator!r}")
    return f"""
let
  {prelude}
  source = {source_expr};
  selectedSystem = {system_expr};
  pkgs = import source {{ system = selectedSystem; }};
  lib = pkgs.lib;
  modulesPath = source + "/nixos/modules";

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
    else throw "Expected a module, a list of modules, or an attrset shaped like flake.nixosModules.";

  render = value:
    let
      modules = moduleValues value;
      eval = {eval_expr};
      docs = pkgs.nixosOptionsDoc {{
        inherit (eval) options;
        warningsAreErrors = false;
      }};
      options = docs.optionsNix;
    in {{
      ok = true;
      mode = {mode_json};
      system = selectedSystem;
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
) -> dict[str, Any]:
    runner_provided = runner is not None
    runner = runner or subprocess.run
    cwd = cwd or os.getcwd()
    candidates: list[tuple[str, str]] = []
    attempts: list[dict[str, Any]] = []

    if looks_like_flake_ref(request.expression):
        try:
            metadata, attempt = resolve_flake_metadata(
                request.expression,
                request.allow_fetch,
                runner=runner,
                cwd=cwd,
                timeout=timeout,
            )
            attempts.append(attempt)
            candidates.append(
                ("flake-nixosModules", flake_ref_expr(flake_metadata_identity(metadata), request.system))
            )
        except EvaluationFailure as exc:
            attempts.extend(exc.attempts)
    candidates.append(("expression-nixosModules", module_collection_expr(request.expression, request.system)))

    for mode, nix_expr in candidates:
        if runner_provided:
            command = build_command(nix_expr, request.allow_fetch)
            completed = runner(
                command,
                cwd=cwd,
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        else:
            try:
                command = build_helper_command(request.allow_fetch, cwd)
            except FileNotFoundError:
                command = build_command(nix_expr, request.allow_fetch)
            completed = run_eval(nix_expr, allow_fetch=request.allow_fetch, cwd=cwd, timeout=timeout)
        attempt = {
            "mode": mode,
            "command": command[:7] + ["..."],
            "returncode": completed.returncode,
            "stderr": completed.stderr[-6000:],
        }
        attempts.append(attempt)
        if completed.returncode != 0:
            continue
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            attempt["stdout"] = completed.stdout[-2000:]
            attempt["jsonError"] = str(exc)
            continue
        result.setdefault("mode", mode)
        result.setdefault("diagnostics", [])
        result["diagnostics"].append(
            {
                "level": "info",
                "message": f"Evaluated {result.get('moduleCount', 0)} module(s) in {mode}.",
            }
        )
        result["attempts"] = attempts
        return result

    message = "Could not evaluate expression as a flake .#nixosModules output or a nixosModules-shaped expression."
    raise EvaluationFailure(message, attempts)


def evaluate_payload(
    payload: dict[str, Any],
    *,
    runner: Runner | None = None,
    cwd: str | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    request = parse_request(payload)
    return evaluate(request, runner=runner, cwd=cwd, timeout=timeout)
