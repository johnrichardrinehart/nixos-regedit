"""Nix evaluator for NixOS-module-shaped inputs."""

from __future__ import annotations

import json
import os
import re
import subprocess
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


FLAKE_REF_RE = re.compile(r"^[A-Za-z0-9+._:/?=@%~-]+(?:#[A-Za-z0-9+._/?=@%~-]+)?$")


def parse_request(payload: dict[str, Any]) -> EvaluationRequest:
    expression = payload.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("expression is required")
    allow_fetch = payload.get("allowFetch", False)
    if not isinstance(allow_fetch, bool):
        raise ValueError("allowFetch must be a boolean")
    return EvaluationRequest(expression=expression.strip(), allow_fetch=allow_fetch)


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


def flake_ref_expr(ref: str) -> str:
    return _wrap_input(
        f'(builtins.getFlake {json.dumps(ref)}).nixosModules',
        "flake-nixosModules",
    )


def module_collection_expr(expression: str) -> str:
    return _wrap_input(f"({expression})", "expression-nixosModules")


def _wrap_input(input_expr: str, mode: str) -> str:
    mode_json = json.dumps(mode)
    return f"""
let
  pkgs = import <nixpkgs> {{ system = builtins.currentSystem; }};
  lib = pkgs.lib;

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
      eval = lib.evalModules {{
        specialArgs = {{
          inherit pkgs lib;
          modulesPath = toString (pkgs.path + "/nixos/modules");
        }};
        inherit modules;
      }};
      docs = pkgs.nixosOptionsDoc {{
        inherit (eval) options;
        warningsAreErrors = false;
      }};
      options = docs.optionsNix;
    in {{
      ok = true;
      mode = {mode_json};
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
    runner = runner or subprocess.run
    cwd = cwd or os.getcwd()
    candidates: list[tuple[str, str]] = []

    if looks_like_flake_ref(request.expression):
        candidates.append(("flake-nixosModules", flake_ref_expr(request.expression)))
    candidates.append(("expression-nixosModules", module_collection_expr(request.expression)))

    attempts: list[dict[str, Any]] = []
    for mode, nix_expr in candidates:
        command = build_command(nix_expr, request.allow_fetch)
        completed = runner(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
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
