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
          nixEmscriptenComponents = import ./nix/emscripten-nix-components.nix { inherit pkgs; };
          nixEmscriptenLinkInputs = [
            nixEmscriptenComponents.libs.nix-util
            nixEmscriptenComponents.libs.nix-util-c
            nixEmscriptenComponents.libs.nix-store
            nixEmscriptenComponents.libs.nix-store-c
            nixEmscriptenComponents.libs.nix-fetchers
            nixEmscriptenComponents.libs.nix-fetchers-c
            nixEmscriptenComponents.libs.nix-expr
            nixEmscriptenComponents.libs.nix-expr-c
            nixEmscriptenComponents.libs.nix-flake
            nixEmscriptenComponents.libs.nix-flake-c
            pkgs.boost
            pkgs.brotli
            pkgs.curl
            pkgs.libarchive
            pkgs.libblake3
            pkgs.libgit2
            pkgs.libsodium
            pkgs.openssl
            pkgs.sqlite
            pkgs.onetbb
          ];
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
          eval-helper = pkgs.stdenv.mkDerivation {
            pname = "nixos-regedit-eval-helper";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [ pkgs.pkg-config ];
            buildInputs = [
              pkgs.nix.dev
              pkgs.nix
            ];
            buildPhase = ''
              runHook preBuild
              $CXX -std=c++23 -O2 src/nixos-regedit-eval-helper.cc \
                $(pkg-config --cflags --libs nix-expr-c nix-flake-c nix-store-c nix-util-c) \
                -o nixos-regedit-eval-helper
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -Dm755 nixos-regedit-eval-helper $out/bin/nixos-regedit-eval-helper
              runHook postInstall
            '';
          };
          browser-evaluator-smoke = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit-browser-evaluator-smoke";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [ pkgs.emscripten ];
            buildPhase = ''
              runHook preBuild
              HOME=$TMPDIR
              mkdir -p .emscriptencache
              export EM_CACHE=$(pwd)/.emscriptencache
              emcc src/browser-evaluator-smoke.c -O2 \
                -sMODULARIZE=1 \
                -sEXPORT_NAME=createNixosRegeditEvaluatorSmoke \
                -sSINGLE_FILE=1 \
                -sEXPORTED_FUNCTIONS='["_nixos_regedit_eval_smoke"]' \
                -sEXPORTED_RUNTIME_METHODS='["cwrap","UTF8ToString"]' \
                -o nixos-regedit-evaluator-smoke.js
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -Dm644 nixos-regedit-evaluator-smoke.js \
                $out/share/nixos-regedit/nixos-regedit-evaluator-smoke.js
              runHook postInstall
            '';
          };
          browser-evaluator-nix-attempt = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit-browser-evaluator-nix-attempt";
            version = "0.1.0";
            src = ./.;
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
                src/browser-evaluator-nix.cc \
                ${pkgs.lib.concatStringsSep " " nixEmscriptenArchives} \
                -sMODULARIZE=1 \
                -sEXPORT_NAME=createNixosRegeditEvaluator \
                -sSINGLE_FILE=1 \
                -sFORCE_FILESYSTEM=1 \
                -sALLOW_MEMORY_GROWTH=1 \
                -sSTACK_SIZE=8388608 \
                -sASSERTIONS=2 \
                -sDISABLE_EXCEPTION_CATCHING=0 \
                -sERROR_ON_UNDEFINED_SYMBOLS=1 \
                -sEXPORTED_FUNCTIONS='["_nixos_regedit_eval_nix","_nixos_regedit_current_system","_malloc","_free"]' \
                -sEXPORTED_RUNTIME_METHODS='["cwrap","UTF8ToString","getExceptionMessage","FS","IDBFS","ENV"]' \
                -lidbfs.js \
                -o nixos-regedit-evaluator.js
              runHook postBuild
            '';
            installPhase = ''
              runHook preInstall
              install -Dm644 nixos-regedit-evaluator.js \
                $out/share/nixos-regedit/nixos-regedit-evaluator.js
              runHook postInstall
            '';
          };
          nix-util-c-emscripten-meson-probe = nixEmscriptenComponents.libs.nix-util-c.overrideAttrs (old: {
            pname = "nixos-regedit-nix-util-c-emscripten-meson-probe";
            meta = (old.meta or { }) // {
              description = "Probe build for Nix's nix-util-c component through an Emscripten Meson cross file";
            };
          });
          nix-store-c-emscripten-meson-probe = nixEmscriptenComponents.libs.nix-store-c.overrideAttrs (old: {
            pname = "nixos-regedit-nix-store-c-emscripten-meson-probe";
            meta = (old.meta or { }) // {
              description = "Probe build for Nix's nix-store-c component through an Emscripten Meson cross file";
            };
          });
          nix-fetchers-c-emscripten-meson-probe = nixEmscriptenComponents.libs.nix-fetchers-c.overrideAttrs (old: {
            pname = "nixos-regedit-nix-fetchers-c-emscripten-meson-probe";
            meta = (old.meta or { }) // {
              description = "Probe build for Nix's nix-fetchers-c component through an Emscripten Meson cross file";
            };
          });
          nix-expr-c-emscripten-meson-probe = nixEmscriptenComponents.libs.nix-expr-c.overrideAttrs (old: {
            pname = "nixos-regedit-nix-expr-c-emscripten-meson-probe";
            meta = (old.meta or { }) // {
              description = "Probe build for Nix's nix-expr-c component through an Emscripten Meson cross file";
            };
          });
          nix-flake-c-emscripten-meson-probe = nixEmscriptenComponents.libs.nix-flake-c.overrideAttrs (old: {
            pname = "nixos-regedit-nix-flake-c-emscripten-meson-probe";
            meta = (old.meta or { }) // {
              description = "Probe build for Nix's nix-flake-c component through an Emscripten Meson cross file";
            };
          });
          standalone = pkgs.stdenvNoCC.mkDerivation {
            pname = "nixos-regedit";
            version = "0.1.0";
            src = ./.;
            nativeBuildInputs = [
              pkgs.makeWrapper
              pkgs.python3
            ];
            installPhase = ''
              runHook preInstall
              python tools/build_standalone.py \
                --static-dir nixos_regedit/static \
                --evaluator-js ${browser-evaluator-nix-attempt}/share/nixos-regedit/nixos-regedit-evaluator.js \
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
          inherit eval-helper;
          inherit browser-evaluator-smoke;
          inherit browser-evaluator-nix-attempt;
          inherit nix-util-c-emscripten-meson-probe;
          inherit nix-store-c-emscripten-meson-probe;
          inherit nix-fetchers-c-emscripten-meson-probe;
          inherit nix-expr-c-emscripten-meson-probe;
          inherit nix-flake-c-emscripten-meson-probe;
          inherit standalone;

          default = standalone;
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
                self.packages.${system}.eval-helper
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
              self.packages.${system}.eval-helper
              pkgs.nix
              pkgs.pkg-config
              pkgs.python3
            ];
            NIX_PATH = "nixpkgs=${nixpkgs}";
          };
        }
      );
    };
}
