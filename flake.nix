{
  description = "Local Registry Editor-style browser for NixOS module options";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "x86_64-linux"
        "aarch64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [ pkgs.makeWrapper ];
            installPhase = ''
              runHook preInstall
              mkdir -p $out/lib/nixos-regedit $out/bin
              cp -r nixos_regedit $out/lib/nixos-regedit/
              makeWrapper ${pkgs.python3}/bin/python $out/bin/nixos-regedit \
                --add-flags "-m nixos_regedit.server" \
                --prefix PYTHONPATH : "$out/lib/nixos-regedit" \
                --prefix PATH : ${nixpkgs.lib.makeBinPath [ pkgs.nix ]} \
                --set NIX_PATH nixpkgs=${nixpkgs}
              runHook postInstall
            '';
          };
        }
      );

      apps = forAllSystems (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/nixos-regedit";
        };
      });

      checks = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        {
          unit = pkgs.runCommand "nixos-regedit-tests"
            {
              nativeBuildInputs = [
                pkgs.nix
                pkgs.python3
              ];
              NIX_PATH = "nixpkgs=${nixpkgs}";
              NIXOS_REGEDIT_SKIP_NIX_INTEGRATION = "1";
            }
            ''
              cp -r ${./.} source
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
          pkgs = import nixpkgs { inherit system; };
        in
        {
          default = pkgs.mkShell {
            packages = [
              pkgs.nix
              pkgs.python3
            ];
            NIX_PATH = "nixpkgs=${nixpkgs}";
          };
        }
      );
    };
}
