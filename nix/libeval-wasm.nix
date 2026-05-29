{
  pkgs,
  src,
  nixEmscriptenComponents,
  documentation ? null,
}:

let
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
in
pkgs.stdenvNoCC.mkDerivation {
  pname = "libeval-wasm";
  version = "0.1.0";
  inherit src;

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
      libeval-wasm.cc \
      ${pkgs.lib.concatStringsSep " " nixEmscriptenArchives} \
      -sMODULARIZE=1 \
      -sEXPORT_NAME=createLibevalWasm \
      -sSINGLE_FILE=1 \
      -sFORCE_FILESYSTEM=1 \
      -sINITIAL_MEMORY=268435456 \
      -sMAXIMUM_MEMORY=1073741824 \
      -sALLOW_MEMORY_GROWTH=1 \
      -sSTACK_SIZE=134217728 \
      -sASSERTIONS=0 \
      -sDISABLE_EXCEPTION_CATCHING=0 \
      -sERROR_ON_UNDEFINED_SYMBOLS=1 \
      -sEXPORTED_FUNCTIONS='["_libeval_wasm","_libeval_wasm_current_system","_malloc","_free"]' \
      -sEXPORTED_RUNTIME_METHODS='["cwrap","UTF8ToString","getExceptionMessage","FS","IDBFS","ENV"]' \
      -lidbfs.js \
      -o libeval.js
    runHook postBuild
  '';

  installPhase = ''
    runHook preInstall
    install -Dm644 libeval.js $out/share/libeval-wasm/libeval.js
    ${pkgs.lib.optionalString (documentation != null) ''
      install -Dm644 ${documentation} $out/share/doc/libeval-wasm/README.md
    ''}
    runHook postInstall
  '';

  passthru = {
    jsPath = "share/libeval-wasm/libeval.js";
  };
}
