import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from nixos_regedit.evaluator import (
    EvaluationRequest,
    build_command,
    evaluate,
    looks_like_flake_ref,
)


def completed(payload):
    return subprocess.CompletedProcess(["nix"], 0, json.dumps(payload), "")


class EvaluatorUnitTests(unittest.TestCase):
    def test_offline_flag_tracks_allow_fetch(self):
        self.assertIn("--offline", build_command("1", allow_fetch=False))
        self.assertNotIn("--offline", build_command("1", allow_fetch=True))

    def test_flake_ref_detection_is_conservative(self):
        self.assertTrue(looks_like_flake_ref("github:owner/repo"))
        self.assertTrue(looks_like_flake_ref("/tmp/example"))
        self.assertFalse(looks_like_flake_ref("{ default = {}; }"))
        self.assertFalse(looks_like_flake_ref("let x = 1; in x"))

    def test_expression_mode_is_used_for_non_flake_expression(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return completed({"ok": True, "options": {}, "optionCount": 0, "moduleCount": 0})

        result = evaluate(EvaluationRequest("{ default = {}; }"), runner=runner)
        self.assertEqual(result["mode"], "expression-nixosModules")
        self.assertEqual(len(calls), 1)

    def test_flake_like_input_falls_back_to_expression(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return subprocess.CompletedProcess(command, 1, "", "no flake")
            return completed({"ok": True, "options": {}, "optionCount": 0, "moduleCount": 0})

        result = evaluate(EvaluationRequest("demo"), runner=runner)
        self.assertEqual(result["mode"], "expression-nixosModules")
        self.assertEqual(len(calls), 2)


class EvaluatorIntegrationTests(unittest.TestCase):
    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_expression_attrset_of_modules(self):
        expr = r'''
        {
          default = { lib, ... }: {
            options.demo.enable = lib.mkEnableOption "demo";
          };
        }
        '''
        result = evaluate(EvaluationRequest(textwrap.dedent(expr)), timeout=180)
        self.assertIn("demo.enable", result["options"])
        self.assertEqual(result["mode"], "expression-nixosModules")

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_expression_list_of_modules(self):
        expr = r'''
        [
          ({ lib, ... }: {
            options.demo.name = lib.mkOption {
              type = lib.types.str;
              default = "sample";
              description = "Sample name.";
            };
          })
        ]
        '''
        result = evaluate(EvaluationRequest(textwrap.dedent(expr)), timeout=180)
        self.assertEqual(result["options"]["demo.name"]["default"]["text"], '"sample"')

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_local_flake_nixos_modules(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            path.joinpath("flake.nix").write_text(
                textwrap.dedent(
                    """
                    {
                      outputs = { self }: {
                        nixosModules.default = { lib, ... }: {
                          options.demo.count = lib.mkOption {
                            type = lib.types.int;
                            default = 7;
                            description = "Demo count.";
                          };
                        };
                      };
                    }
                    """
                )
            )
            result = evaluate(EvaluationRequest(os.fspath(path)), timeout=180)
            self.assertEqual(result["mode"], "flake-nixosModules")
            self.assertEqual(result["options"]["demo.count"]["default"]["text"], "7")


if __name__ == "__main__":
    unittest.main()
