import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from nixos_regedit.evaluator import (
    EvaluationFailure,
    EvaluationRequest,
    build_command,
    build_flake_metadata_command,
    evaluate,
    flake_ref_expr,
    looks_like_flake_ref,
    module_collection_expr,
    normalize_flake_ref,
    parse_request,
    resolve_payload,
)


def completed(payload):
    return subprocess.CompletedProcess(["nix"], 0, json.dumps(payload), "")


class EvaluatorUnitTests(unittest.TestCase):
    def test_system_override_is_optional(self):
        self.assertIsNone(parse_request({"expression": "{}", "system": ""}).system)
        self.assertEqual(
            parse_request({"expression": "{}", "system": "aarch64-linux"}).system,
            "aarch64-linux",
        )

    def test_offline_flag_tracks_allow_fetch(self):
        self.assertIn("--offline", build_command("1", allow_fetch=False))
        self.assertNotIn("--offline", build_command("1", allow_fetch=True))
        self.assertIn(
            "--offline", build_flake_metadata_command("github:owner/repo", allow_fetch=False)
        )
        self.assertNotIn(
            "--offline", build_flake_metadata_command("github:owner/repo", allow_fetch=True)
        )

    def test_resolve_expression_identity_without_flake_metadata(self):
        result = resolve_payload({"expression": "{ default = {}; }", "system": "x86_64-linux"})
        self.assertEqual(result["kind"], "expression")
        self.assertEqual(result["identity"], "{ default = {}; }")
        self.assertEqual(result["system"], "x86_64-linux")

    def test_resolve_flake_identity_uses_metadata_url(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return completed({"url": "github:owner/repo/rev?narHash=sha256-test"})

        result = resolve_payload(
            {"expression": "github:owner/repo", "allowFetch": True, "system": "x86_64-linux"},
            runner=runner,
        )
        self.assertEqual(result["kind"], "flake")
        self.assertEqual(result["identity"], "github:owner/repo/rev?narHash=sha256-test")
        self.assertEqual(calls[0][-3:], ["metadata", "--json", "github:owner/repo"])

    def test_fetch_disabled_refuses_unpinned_remote_flake_before_nix(self):
        def runner(command, **kwargs):
            self.fail("runner should not be called for unlocked remote flakes with fetch disabled")

        with self.assertRaises(EvaluationFailure):
            resolve_payload(
                {"expression": "github:owner/repo", "allowFetch": False, "system": "x86_64-linux"},
                runner=runner,
            )

    def test_flake_ref_detection_is_conservative(self):
        self.assertTrue(looks_like_flake_ref("github:owner/repo"))
        self.assertTrue(looks_like_flake_ref("/tmp/example"))
        self.assertFalse(looks_like_flake_ref("{ default = {}; }"))
        self.assertFalse(looks_like_flake_ref("let x = 1; in x"))

    def test_existing_local_flake_refs_are_normalized_to_path_refs(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(normalize_flake_ref(tmp, "/"), f"path:{tmp}")
            self.assertEqual(normalize_flake_ref(".", tmp), f"path:{tmp}")
        self.assertEqual(normalize_flake_ref("github:owner/repo", "/"), "github:owner/repo")

    def test_expression_mode_is_used_for_non_flake_expression(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return completed({"ok": True, "options": {}, "optionCount": 0, "moduleCount": 0})

        result = evaluate(
            EvaluationRequest("{ default = {}; }", system="aarch64-linux"), runner=runner
        )
        self.assertEqual(result["mode"], "expression-nixosModules")
        self.assertIn('"aarch64-linux"', calls[0][-1])
        self.assertEqual(len(calls), 1)

    def test_module_wrapper_uses_vendored_doc_renderer_and_sliced_lib(self):
        expr = module_collection_expr("{ default = {}; }", "x86_64-linux")
        self.assertIn("support.lib.nixpkgsLib", expr)
        self.assertIn("support.lib.nixosOptionsDoc", expr)
        self.assertNotIn("<nixpkgs>", expr)
        self.assertNotIn("pkgs.nixosOptionsDoc", expr)
        self.assertNotIn("/nixos/lib/eval-config.nix", expr)

        flake_expr = flake_ref_expr("github:owner/repo/rev?narHash=sha256-test", "x86_64-linux")
        self.assertIn("support.lib.nixpkgsLib", flake_expr)
        self.assertNotIn("<nixpkgs>", flake_expr)

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
    def test_expression_single_module(self):
        expr = r"""
        { lib, ... }: {
          options.demo.single = lib.mkEnableOption "single module";
        }
        """
        result = evaluate(EvaluationRequest(textwrap.dedent(expr)), timeout=180)
        self.assertIn("demo.single", result["options"])
        self.assertNotIn("services.nginx.enable", result["options"])
        self.assertLess(result["optionCount"], 10)
        self.assertEqual(result["mode"], "expression-nixosModules")

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_expression_attrset_of_modules(self):
        expr = r"""
        {
          default = { lib, ... }: {
            options.demo.enable = lib.mkEnableOption "demo";
          };
        }
        """
        result = evaluate(EvaluationRequest(textwrap.dedent(expr)), timeout=180)
        self.assertIn("demo.enable", result["options"])
        self.assertNotIn("services.nginx.enable", result["options"])
        self.assertLess(result["optionCount"], 10)
        self.assertEqual(result["mode"], "expression-nixosModules")

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_expression_list_of_modules(self):
        expr = r"""
        [
          ({ lib, ... }: {
            options.demo.name = lib.mkOption {
              type = lib.types.str;
              default = "sample";
              description = "Sample name.";
            };
          })
        ]
        """
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
