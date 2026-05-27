{
  description = "Local Registry Editor-style browser for NixOS module options";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs";
    git-hooks = {
      url = "github:cachix/git-hooks.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      git-hooks,
      treefmt-nix,
    }:
    let
      fs = nixpkgs.lib.fileset;
      systems = [
        "x86_64-linux"
      ];
      projectFileset = fs.unions [
        ./.clang-format
        ./.envrc
        ./.github
        ./.gitignore
        ./README.md
        ./docs
        ./flake.lock
        ./flake.nix
        ./lib
        ./nix
        ./nixos_regedit
        ./pyproject.toml
        ./src
        ./tests
        ./tools
        ./treefmt.nix
      ];
      qualityFileset = fs.unions [
        projectFileset
        ./infra
      ];
      qualitySource = fs.toSource {
        root = ./.;
        fileset = qualityFileset;
      };
      supportFlakeSource = fs.toSource {
        root = ./.;
        fileset = fs.unions [
          ./flake.lock
          ./flake.nix
          ./lib
          ./nix
          ./nixos_regedit
          ./src
          ./tools
        ];
      };
      evaluatorSource = fs.toSource {
        root = ./src;
        fileset = ./src/libeval-wasm.cc;
      };
      standaloneSource = fs.toSource {
        root = ./.;
        fileset = fs.unions [
          ./nixos_regedit/static
          ./tools/build_standalone.py
        ];
      };
      backendSource = fs.toSource {
        root = ./.;
        fileset = ./nixos_regedit;
      };
      testSource = fs.toSource {
        root = ./.;
        fileset = fs.unions [
          ./.github/workflows/pages.yml
          ./infra/cloudflare/workers/archive-proxy.js
          ./lib
          ./nixos_regedit
          ./src/libeval-wasm.cc
          ./tests
          ./tools/build_standalone.py
        ];
      };
      nixpkgsLibSource =
        let
          libPrefix = "${nixpkgs}/lib";
        in
        nixpkgs.lib.sources.cleanSourceWith {
          src = nixpkgs;
          filter = path: _type: path == libPrefix || nixpkgs.lib.hasPrefix "${libPrefix}/" path;
        };
      nixpkgsLibFileset = fs.fromSource nixpkgsLibSource;
      nixpkgsLib = import "${nixpkgsLibSource}/lib";
      forAllSystems = nixpkgs.lib.genAttrs systems;
      pkgsFor = system: import nixpkgs { inherit system; };
      treefmtEval =
        system:
        let
          pkgs = pkgsFor system;
        in
        treefmt-nix.lib.evalModule pkgs ./treefmt.nix;
      preCommitCheck =
        system:
        let
          pkgs = pkgsFor system;
        in
        git-hooks.lib.${system}.run {
          src = qualitySource;
          hooks = {
            actionlint.enable = true;
            check-json.enable = true;
            check-merge-conflicts.enable = true;
            check-python.enable = true;
            check-symlinks.enable = true;
            check-toml.enable = true;
            treefmt = {
              enable = true;
              packageOverrides.treefmt = (treefmtEval system).config.build.wrapper;
            };
            deadnix.enable = true;
            statix.enable = true;
            check-yaml.enable = true;
            "ruff-check" = {
              enable = true;
              name = "ruff check";
              entry = "${pkgs.ruff}/bin/ruff check";
              files = "\\.py$";
              types = [ "python" ];
            };
          };
        };
    in
    {
      lib = {
        nixosOptionsDoc = import ./lib/nixos-options-doc.nix;
        inherit nixpkgsLib nixpkgsLibFileset nixpkgsLibSource;
      };

      packages = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          nixEmscriptenComponents = import ./nix/emscripten-nix-components.nix { inherit pkgs; };
          libevalWasm = import ./nix/libeval-wasm.nix {
            inherit pkgs nixEmscriptenComponents;
            src = evaluatorSource;
            documentation = ./docs/libeval-wasm.md;
          };
          backend = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit-server";
            version = "0.1.0";
            src = backendSource;
            nativeBuildInputs = [ pkgs.makeWrapper ];
            installPhase = ''
              runHook preInstall
              mkdir -p $out/lib/nixos-regedit $out/bin
              cp -r nixos_regedit $out/lib/nixos-regedit/
              makeWrapper ${pkgs.python3}/bin/python $out/bin/nixos-regedit \
                --add-flags "-m nixos_regedit.server" \
                --prefix PYTHONPATH : "$out/lib/nixos-regedit" \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.nix ]} \
                --set NIX_PATH nixpkgs=${nixpkgs} \
                --set NIXOS_REGEDIT_FLAKE_REF path:${supportFlakeSource}
              runHook postInstall
            '';
          };
          standalone = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit";
            version = "0.1.0";
            src = standaloneSource;
            nativeBuildInputs = [
              pkgs.python3
            ];
            installPhase = ''
              runHook preInstall
              python tools/build_standalone.py \
                --static-dir nixos_regedit/static \
                --evaluator-js ${self.packages.${system}.libeval-wasm}/share/libeval-wasm/libeval-wasm.js \
                --out $out/share/nixos-regedit/index.html
              mkdir -p $out/bin
              cat > $out/bin/nixos-regedit <<EOF
              #!${pkgs.runtimeShell}
              set -eu
              html="$out/share/nixos-regedit/index.html"
              if command -v xdg-open >/dev/null 2>&1; then
                exec xdg-open "\$html"
              elif command -v open >/dev/null 2>&1; then
                exec open "\$html"
              elif command -v brave >/dev/null 2>&1; then
                exec brave "file://\$html"
              elif command -v chromium >/dev/null 2>&1; then
                exec chromium "file://\$html"
              elif command -v firefox >/dev/null 2>&1; then
                exec firefox "file://\$html"
              fi
              printf '%s\n' "\$html"
              EOF
              chmod +x $out/bin/nixos-regedit
              ln -s $out/share/nixos-regedit/index.html $out/index.html
              runHook postInstall
            '';
          };
        in
        {
          libeval-wasm = libevalWasm;
          inherit backend standalone;

          default = standalone;
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.backend}/bin/nixos-regedit";
          meta.description = "Run the local Python-backed NixOS Regedit server";
        };
        backend = {
          type = "app";
          program = "${self.packages.${system}.backend}/bin/nixos-regedit";
          meta.description = "Run the local Python-backed NixOS Regedit server";
        };
        standalone = {
          type = "app";
          program = "${self.packages.${system}.standalone}/bin/nixos-regedit";
          meta.description = "Open the built standalone NixOS Regedit HTML";
        };
      });

      formatter = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          treefmtWrapper = (treefmtEval system).config.build.wrapper;
          preCommit = preCommitCheck system;
        in
        pkgs.writeShellApplication {
          name = "nixos-regedit-format";
          runtimeInputs = [
            treefmtWrapper
            preCommit.config.package
          ];
          text = ''
            treefmt "$@"
            if [ "$#" -eq 0 ]; then
              pre-commit run -c ${preCommit.config.configFile} --all-files
            else
              pre-commit run -c ${preCommit.config.configFile} --files "$@"
            fi
          '';
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
        in
        {
          formatting = (treefmtEval system).config.build.check qualitySource;
          pre-commit = preCommitCheck system;
          libeval-wasm = self.packages.${system}.libeval-wasm;
          standalone = self.packages.${system}.standalone;
          unit =
            pkgs.runCommand "nixos-regedit-tests"
              {
                nativeBuildInputs = [
                  pkgs.nix
                  pkgs.python3
                ];
                NIX_PATH = "nixpkgs=${nixpkgs}";
                NIXOS_REGEDIT_SKIP_NIX_INTEGRATION = "1";
              }
              ''
                cp -r ${testSource} source
                chmod -R u+w source
                cd source
                python -m unittest discover -s tests -v
                touch $out
              '';
        }
      );

      devShells = forAllSystems (
        system:
        let
          pkgs = pkgsFor system;
          preCommit = preCommitCheck system;
        in
        {
          default = pkgs.mkShell {
            packages = preCommit.enabledPackages ++ [
              self.formatter.${system}
              (treefmtEval system).config.build.wrapper
              pkgs.clang-tools
              pkgs.deadnix
              pkgs.prettier
              pkgs.ruff
              pkgs.statix
              pkgs.taplo
              pkgs.nix
              pkgs.opentofu
              pkgs.pkg-config
              pkgs.python3
            ];
            inherit (preCommit) shellHook;
            NIX_PATH = "nixpkgs=${nixpkgs}";
          };
        }
      );
    };
}
