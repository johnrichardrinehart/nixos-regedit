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
      projectSource = fs.toSource {
        root = ./.;
        fileset = projectFileset;
      };
      evaluatorSource = fs.toSource {
        root = ./src;
        fileset = ./src/browser-evaluator-nix.cc;
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
          ./lib
          ./nixos_regedit
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
          src = projectSource;
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
          nixEmscriptenCIncludes = [
            nixEmscriptenComponents.libs.nix-util-c.dev
            nixEmscriptenComponents.libs.nix-store-c.dev
            nixEmscriptenComponents.libs.nix-fetchers-c.dev
            nixEmscriptenComponents.libs.nix-expr-c.dev
            nixEmscriptenComponents.libs.nix-flake-c.dev
          ];
          emscriptenSqlite = pkgs.stdenvNoCC.mkDerivation {
            pname = "sqlite-emscripten";
            version = "3.39.0";
            src = pkgs.fetchzip {
              url = "https://www.sqlite.org/2022/sqlite-amalgamation-3390000.zip";
              hash = "sha512-igN3h8Rp0p/Z+GQYdUIHqfUHLYP/nrKGS5HLQhFOtIep0vLFwgEnP1Gp5RAix+3gKVEqnGKfBSWoXKwC680HXg==";
            };
            nativeBuildInputs = [ pkgs.emscripten ];
            buildPhase = ''
              runHook preBuild
              HOME=$TMPDIR
              mkdir -p .emscriptencache
              export EM_CACHE=$(pwd)/.emscriptencache
              emcc -O2 \
                -DSTDC_HEADERS=1 \
                -DHAVE_SYS_TYPES_H=1 \
                -DHAVE_SYS_STAT_H=1 \
                -DHAVE_STDLIB_H=1 \
                -DHAVE_STRING_H=1 \
                -DHAVE_MEMORY_H=1 \
                -DHAVE_STRINGS_H=1 \
                -DHAVE_INTTYPES_H=1 \
                -DHAVE_STDINT_H=1 \
                -DHAVE_UNISTD_H=1 \
                -DHAVE_FDATASYNC=1 \
                -DHAVE_USLEEP=1 \
                -DHAVE_LOCALTIME_R=1 \
                -DHAVE_GMTIME_R=1 \
                -DHAVE_DECL_STRERROR_R=1 \
                -DHAVE_STRERROR_R=1 \
                -DHAVE_POSIX_FALLOCATE=1 \
                -DSQLITE_OMIT_LOAD_EXTENSION=1 \
                -DSQLITE_ENABLE_MATH_FUNCTIONS=1 \
                -DSQLITE_ENABLE_FTS4=1 \
                -DSQLITE_ENABLE_FTS5=1 \
                -DSQLITE_ENABLE_RTREE=1 \
                -DSQLITE_ENABLE_GEOPOLY=1 \
                -DSQLITE_OMIT_POPEN=1 \
                -DSQLITE_THREADSAFE=0 \
                -c sqlite3.c -o sqlite3.o
              emar rcs libsqlite3.a sqlite3.o
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -Dm644 libsqlite3.a $out/lib/libsqlite3.a
              install -Dm644 sqlite3.h $out/include/sqlite3.h
              install -Dm644 sqlite3ext.h $out/include/sqlite3ext.h
              runHook postInstall
            '';
          };
          wholeArchive = archive: "-Wl,--whole-archive ${archive} -Wl,--no-whole-archive";
          nixEmscriptenArchives = [
            (wholeArchive "${nixEmscriptenComponents.libs.nix-flake-c}/lib/libnixflakec.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-flake}/lib/libnixflake.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-expr-c}/lib/libnixexprc.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-expr}/lib/libnixexpr.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-fetchers}/lib/libnixfetchers.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-fetchers-c}/lib/libnixfetchersc.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-store-c}/lib/libnixstorec.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-store}/lib/libnixstore.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-util-c}/lib/libnixutilc.a")
            (wholeArchive "${nixEmscriptenComponents.libs.nix-util}/lib/libnixutil.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.boost}/lib/libboost_url.a")
            # boost_iostreams registers optional compression filters. Whole-archiving
            # it can pull in backends we intentionally do not ship in the browser build.
            "${nixEmscriptenComponents.emscriptenDeps.boost}/lib/libboost_iostreams.a"
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.brotli}/lib/libbrotlienc.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.brotli}/lib/libbrotlidec.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.brotli}/lib/libbrotlicommon.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.libarchive}/lib/libarchive.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.libgit2}/lib/libgit2.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.blake3}/lib/libblake3.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.xz}/lib/liblzma.a")
            (wholeArchive "${nixEmscriptenComponents.emscriptenDeps.zlib}/lib/libz.a")
            (wholeArchive "${emscriptenSqlite}/lib/libsqlite3.a")
          ];
          nixBrowserEvaluator = pkgs.stdenvNoCC.mkDerivation {
            pname = "nix-browser-evaluator";
            version = "0.1.0";
            src = evaluatorSource;
            nativeBuildInputs = [
              pkgs.emscripten
            ];
            buildInputs = [
              nixEmscriptenComponents.libs.nix-expr-c
              nixEmscriptenComponents.emscriptenDeps.boost
            ];
            buildPhase = ''
              runHook preBuild
              HOME=$TMPDIR
              mkdir -p .emscriptencache
              export EM_CACHE=$(pwd)/.emscriptencache
              em++ -std=c++23 -O2 -fexceptions \
                ${pkgs.lib.concatMapStringsSep " " (input: "-I${input}/include") nixEmscriptenCIncludes} \
                browser-evaluator-nix.cc \
                ${pkgs.lib.concatStringsSep " " nixEmscriptenArchives} \
                -sMODULARIZE=1 \
                -sEXPORT_NAME=createNixBrowserEvaluator \
                -sSINGLE_FILE=1 \
                -sFORCE_FILESYSTEM=1 \
                -sALLOW_MEMORY_GROWTH=1 \
                -sSTACK_SIZE=8388608 \
                -sASSERTIONS=2 \
                -sDISABLE_EXCEPTION_CATCHING=0 \
                -sERROR_ON_UNDEFINED_SYMBOLS=1 \
                -sEXPORTED_FUNCTIONS='["_libeval_wasm","_libeval_wasm_current_system","_malloc","_free"]' \
                -sEXPORTED_RUNTIME_METHODS='["cwrap","UTF8ToString","getExceptionMessage","FS","IDBFS","ENV"]' \
                -lidbfs.js \
                -o nix-browser-evaluator.js
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -Dm644 nix-browser-evaluator.js \
                $out/share/nix-browser-evaluator/nix-browser-evaluator.js
              mkdir -p $out/share/nixos-regedit
              ln -s ../nix-browser-evaluator/nix-browser-evaluator.js \
                $out/share/nixos-regedit/nixos-regedit-evaluator.js
              runHook postInstall
            '';
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
                --set NIXOS_REGEDIT_FLAKE_REF path:${projectSource}
              runHook postInstall
            '';
          };
          standalone = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit";
            version = "0.1.0";
            src = standaloneSource;
            nativeBuildInputs = [
              pkgs.makeWrapper
              pkgs.python3
            ];
            installPhase = ''
              runHook preInstall
              python tools/build_standalone.py \
                --static-dir nixos_regedit/static \
                --evaluator-js ${nixBrowserEvaluator}/share/nix-browser-evaluator/nix-browser-evaluator.js \
                --out $out/share/nixos-regedit/index.html
              mkdir -p $out/bin
              makeWrapper ${pkgs.coreutils}/bin/printf $out/bin/nixos-regedit \
                --add-flags "Open $out/share/nixos-regedit/index.html in a browser.\\n"
              ln -s $out/share/nixos-regedit/index.html $out/index.html
              runHook postInstall
            '';
          };
        in
        {
          nix-browser-evaluator = nixBrowserEvaluator;
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
          meta.description = "Show the path to the built standalone NixOS Regedit HTML";
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
          formatting = (treefmtEval system).config.build.check projectSource;
          pre-commit = preCommitCheck system;
          browser-evaluator = self.packages.${system}.nix-browser-evaluator;
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
