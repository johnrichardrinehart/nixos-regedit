import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from nixos_regedit.evaluator import (
    REPO_ROOT,
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
        self.assertNotIn("tarball-ttl", build_command("1", allow_fetch=True))
        self.assertNotIn(
            "tarball-ttl", build_flake_metadata_command("github:owner/repo", allow_fetch=True)
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
        self.assertEqual(
            result["identity"], "github:owner/repo/rev?narHash=sha256-test#nixosModules.default"
        )
        self.assertEqual(calls[0][-3:], ["metadata", "--json", "github:owner/repo"])

    def test_resolve_flake_selector_preserves_selected_output(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return completed({"url": "github:owner/repo/rev?narHash=sha256-test"})

        result = resolve_payload(
            {
                "expression": "github:owner/repo#foo",
                "allowFetch": True,
                "system": "x86_64-linux",
            },
            runner=runner,
        )
        self.assertEqual(result["kind"], "flake")
        self.assertEqual(result["identity"], "github:owner/repo/rev?narHash=sha256-test#foo")
        self.assertEqual(calls[0][-3:], ["metadata", "--json", "github:owner/repo"])

    def test_fetch_disabled_refuses_remote_flake_before_nix(self):
        def runner(command, **kwargs):
            self.fail("runner should not be called for remote flakes with fetch disabled")

        with self.assertRaises(EvaluationFailure):
            resolve_payload(
                {"expression": "github:owner/repo", "allowFetch": False, "system": "x86_64-linux"},
                runner=runner,
            )
        with self.assertRaises(EvaluationFailure):
            resolve_payload(
                {
                    "expression": "github:owner/repo/rev?narHash=sha256-test",
                    "allowFetch": False,
                    "system": "x86_64-linux",
                },
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
            self.assertEqual(
                normalize_flake_ref(f"{tmp}#customModules", "/"), f"path:{tmp}#customModules"
            )
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
        self.assertIn('[ "nixosModules" "default" ]', flake_expr)
        self.assertIn("flake.inputs.nixpkgs.lib ? nixosSystem", flake_expr)
        self.assertIn("modules = modules", flake_expr)
        self.assertNotIn("<nixpkgs>", flake_expr)

        selected_expr = flake_ref_expr(
            "github:owner/repo/rev?narHash=sha256-test#foo.bar", "x86_64-linux"
        )
        self.assertIn('[ "foo" "bar" ]', selected_expr)
        self.assertNotIn(
            'builtins.getFlake "github:owner/repo/rev?narHash=sha256-test#foo.bar"', selected_expr
        )
        self.assertIn('moduleSource = "flake attribute .#foo.bar"', selected_expr)

        attrset_expr = flake_ref_expr(
            "github:owner/repo/rev?narHash=sha256-test#nixosModules", "x86_64-linux"
        )
        self.assertIn('[ "nixosModules" ]', attrset_expr)
        self.assertNotIn('[ "nixosModules" "default" ]', attrset_expr)

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

    def test_flake_evaluation_defaults_to_nixos_modules_and_preserves_selector(self):
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            if command[:1] == ["nix"] and command[-3:-1] == ["metadata", "--json"]:
                return completed({"url": "github:owner/repo/rev?narHash=sha256-test"})
            return completed({"ok": True, "options": {}, "optionCount": 0, "moduleCount": 0})

        result = evaluate(
            EvaluationRequest("github:owner/repo#foo.bar", allow_fetch=True, system="x86_64-linux"),
            runner=runner,
        )

        self.assertEqual(result["mode"], "flake-nixosModules")
        self.assertEqual(calls[0][-3:], ["metadata", "--json", "github:owner/repo"])
        self.assertIn("github:owner/repo/rev?narHash=sha256-test", calls[1][-1])
        self.assertNotIn(
            'builtins.getFlake "github:owner/repo/rev?narHash=sha256-test#foo.bar"',
            calls[1][-1],
        )
        self.assertIn('[ "foo" "bar" ]', calls[1][-1])


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
        self.assertEqual(result["moduleSource"], "input expression")

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
            self.assertEqual(result["moduleSource"], "flake attribute .#nixosModules.default")
            self.assertEqual(result["options"]["demo.count"]["default"]["text"], "7")

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_local_flake_explicit_module_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            path.joinpath("flake.nix").write_text(
                textwrap.dedent(
                    """
                    {
                      outputs = { self }: {
                        customModules.default = { lib, ... }: {
                          options.demo.selected = lib.mkOption {
                            type = lib.types.str;
                            default = "custom";
                            description = "Selected custom output.";
                          };
                        };
                        nixosModules.default = { lib, ... }: {
                          options.demo.unselected = lib.mkEnableOption "unselected output";
                        };
                      };
                    }
                    """
                )
            )
            result = evaluate(EvaluationRequest(f"{path}#customModules"), timeout=180)
            self.assertEqual(result["mode"], "flake-nixosModules")
            self.assertEqual(result["moduleSource"], "flake attribute .#customModules")
            self.assertIn("demo.selected", result["options"])
            self.assertNotIn("demo.unselected", result["options"])

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_local_flake_falls_back_to_module_list_when_default_output_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            modules = path / "nixos" / "modules"
            modules.mkdir(parents=True)
            modules.joinpath("module-list.nix").write_text("[ ./demo.nix ]")
            modules.joinpath("demo.nix").write_text(
                textwrap.dedent(
                    """
                    { lib, ... }: {
                      options.demo.fromModuleList = lib.mkEnableOption "module-list fallback";
                    }
                    """
                )
            )
            path.joinpath("flake.nix").write_text("{ outputs = { self }: { }; }")
            result = evaluate(EvaluationRequest(os.fspath(path)), timeout=180)
            self.assertEqual(result["mode"], "flake-module-list")
            self.assertEqual(result["moduleSource"], "nixos/modules/module-list.nix")
            self.assertIn("demo.fromModuleList", result["options"])

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_local_flake_prefers_nixos_system_before_module_list_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            modules = path / "nixos" / "modules"
            modules.mkdir(parents=True)
            modules.joinpath("module-list.nix").write_text("[ ./module-list-only.nix ]")
            modules.joinpath("module-list-only.nix").write_text(
                textwrap.dedent(
                    """
                    { lib, ... }: {
                      options.demo.fromModuleList = lib.mkEnableOption "module-list fallback";
                    }
                    """
                )
            )
            path.joinpath("flake.nix").write_text(
                textwrap.dedent(
                    """
                    {
                      outputs = { self }: {
                        lib =
                          let
                            baseLib = (builtins.getFlake @ROOT_REF@).lib.nixpkgsLib;
                          in
                          baseLib // {
                            nixosSystem = { system, modules }:
                              baseLib.evalModules {
                                modules = modules ++ [
                                  ({ lib, ... }: {
                                    options.demo.fromNixosSystem =
                                      lib.mkEnableOption "nixosSystem fallback";
                                  })
                                ];
                              };
                          };
                      };
                    }
                    """
                ).replace("@ROOT_REF@", json.dumps("path:" + os.fspath(REPO_ROOT)))
            )
            result = evaluate(EvaluationRequest(os.fspath(path)), timeout=180)
            self.assertEqual(result["mode"], "flake-nixosSystem")
            self.assertEqual(result["moduleSource"], "flake.lib.nixosSystem")
            self.assertIn("demo.fromNixosSystem", result["options"])
            self.assertNotIn("demo.fromModuleList", result["options"])

    @unittest.skipIf(
        os.environ.get("NIXOS_REGEDIT_SKIP_NIX_INTEGRATION") == "1",
        "nix eval inside a Nix build requires recursive-Nix support",
    )
    def test_local_flake_does_not_fall_back_when_default_output_is_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            modules = path / "nixos" / "modules"
            modules.mkdir(parents=True)
            modules.joinpath("module-list.nix").write_text("[ ./demo.nix ]")
            modules.joinpath("demo.nix").write_text(
                textwrap.dedent(
                    """
                    { lib, ... }: {
                      options.demo.fromModuleList = lib.mkEnableOption "module-list fallback";
                    }
                    """
                )
            )
            path.joinpath("flake.nix").write_text(
                "{ outputs = { self }: { nixosModules.default = 1; }; }"
            )
            with self.assertRaises(EvaluationFailure) as caught:
                evaluate(EvaluationRequest(os.fspath(path)), timeout=180)
            self.assertIn(".#nixosModules.default", caught.exception.error)
            self.assertNotIn(
                "flake-module-list", [attempt["mode"] for attempt in caught.exception.attempts]
            )


if __name__ == "__main__":
    unittest.main()
