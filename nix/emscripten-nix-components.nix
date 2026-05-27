{ pkgs }:

let
  emscriptenMesonCrossFile = pkgs.writeText "nixos-regedit-emscripten-meson-cross.ini" ''
    [binaries]
    c = '${pkgs.emscripten}/bin/emcc'
    cpp = '${pkgs.emscripten}/bin/em++'
    ar = '${pkgs.emscripten}/bin/emar'
    strip = '${pkgs.emscripten}/bin/emstrip'
    pkg-config = '${pkgs.pkg-config}/bin/pkg-config'
    cmake = '${pkgs.cmake}/bin/cmake'

    [host_machine]
    system = 'emscripten'
    cpu_family = 'wasm32'
    cpu = 'wasm32'
    endian = 'little'

    [properties]
    needs_exe_wrapper = true

    [built-in options]
    default_library = 'static'
    b_staticpic = false
    # Boehm GC tests _MSVC_LANG without guarding it; Nix builds with
    # -Werror=undef, so define it globally for this non-MSVC Emscripten target.
    cpp_args = ['-D_MSVC_LANG=0', '-fexceptions']
  '';

  nativeDependencyProbeInputs = [
    pkgs.boost.dev
    pkgs.brotli.dev
    pkgs.curl.dev
    pkgs.libarchive.dev
    pkgs.libblake3.dev
    pkgs.libgit2.dev
    pkgs.libsodium.dev
    pkgs.nlohmann_json
    pkgs.openssl.dev
    pkgs.sqlite.dev
    pkgs.toml11
  ];

  emscriptenBoostCxx = pkgs.writeShellScript "emxx-for-boost-b2" ''
    if [ "''${1-}" = "--version" ]; then
      echo "clang version 22.1.6"
      exit 0
    fi
    exec ${pkgs.emscripten}/bin/em++ "$@"
  '';

  emscriptenBoost = (pkgs.boost.override {
    stdenv = pkgs.emscriptenStdenv;
    enableShared = false;
    enableStatic = true;
    enableSingleThreaded = true;
    enableMultiThreaded = false;
    enableIcu = false;
    toolset = "clang";
    extraB2Args = [
      "--with-context"
      "--with-coroutine"
      "--with-iostreams"
      "--with-url"
      "toolset=clang"
    ];
  }).overrideAttrs (old: {
    doCheck = false;
    preConfigure = ''
      cat > user-config.jam <<EOF
      using clang : : ${emscriptenBoostCxx}
        : <archiver>${pkgs.emscripten}/bin/emar
          <ranlib>${pkgs.emscripten}/bin/emranlib
        ;
      EOF
    '';
    configurePhase = ''
      runHook preConfigure
      ./bootstrap.sh \
        --includedir=$dev/include \
        --libdir=$out/lib \
        --with-bjam=b2 \
        --with-toolset=clang \
        --without-icu
      substituteInPlace project-config.jam \
        --replace-fail "using clang ;" \
        "using clang : : ${emscriptenBoostCxx} : <archiver>${pkgs.emscripten}/bin/emar <ranlib>${pkgs.emscripten}/bin/emranlib ;"
      runHook postConfigure
    '';
    preBuild = ''
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache
    '';
    buildPhase = ''
      runHook preBuild
      b2 \
        --includedir=$dev/include \
        --libdir=$out/lib \
        -j$NIX_BUILD_CORES \
        --layout=system \
        variant=release \
        threading=single \
        link=static \
        runtime-link=static \
        debug-symbols=off \
        toolset=clang \
        --with-context \
        --with-coroutine \
        --with-iostreams \
        --with-url
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      mkdir -p $dev/share/boostbook
      cp -a tools/boostbook/{xsl,dtd} $dev/share/boostbook/
      b2 \
        --includedir=$dev/include \
        --libdir=$out/lib \
        -j$NIX_BUILD_CORES \
        --layout=system \
        variant=release \
        threading=single \
        link=static \
        runtime-link=static \
        debug-symbols=off \
        toolset=clang \
        --with-context \
        --with-coroutine \
        --with-iostreams \
        --with-url \
        install
      runHook postInstall
    '';
  });

  emscriptenZlib = pkgs.stdenvNoCC.mkDerivation {
    pname = "zlib-emscripten";
    inherit (pkgs.zlib) version src;
    nativeBuildInputs = [ pkgs.emscripten ];
    configurePhase = ''
      runHook preConfigure
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache
      CC=${pkgs.emscripten}/bin/emcc \
        AR="${pkgs.emscripten}/bin/emar" \
        RANLIB="${pkgs.emscripten}/bin/emranlib" \
        ./configure --static --prefix=$out
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      emmake make libz.a
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      install -Dm644 libz.a $out/lib/libz.a
      install -Dm644 zlib.h $out/include/zlib.h
      install -Dm644 zconf.h $out/include/zconf.h
      runHook postInstall
    '';
  };

  emscriptenXz = pkgs.stdenvNoCC.mkDerivation {
    pname = "xz-emscripten";
    inherit (pkgs.xz) version src;
    nativeBuildInputs = [ pkgs.emscripten ];
    configurePhase = ''
      runHook preConfigure
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache
      CC=${pkgs.emscripten}/bin/emcc \
        AR="${pkgs.emscripten}/bin/emar" \
        RANLIB="${pkgs.emscripten}/bin/emranlib" \
        emconfigure ./configure \
          --host=wasm32-unknown-emscripten \
          --prefix=$out \
          --disable-shared \
          --enable-static \
          --disable-doc \
          --disable-nls \
          --disable-scripts \
          --disable-xz \
          --disable-xzdec \
          --disable-lzmadec \
          --disable-lzmainfo
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      emmake make -C src/liblzma
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      emmake make -C src/liblzma install
      runHook postInstall
    '';
  };

  emscriptenLibarchive = pkgs.stdenvNoCC.mkDerivation {
    pname = "libarchive-emscripten";
    inherit (pkgs.libarchive) version src;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.emscripten
      pkgs.ninja
    ];
    dontUseCmakeConfigure = true;
    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache

      emcmake cmake -S . -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$out \
        -DCMAKE_PREFIX_PATH="${emscriptenZlib};${emscriptenXz}" \
        -DBUILD_SHARED_LIBS=OFF \
        -DZLIB_INCLUDE_DIR=${emscriptenZlib}/include \
        -DZLIB_LIBRARY=${emscriptenZlib}/lib/libz.a \
        -DLIBLZMA_INCLUDE_DIR=${emscriptenXz}/include \
        -DLIBLZMA_LIBRARY=${emscriptenXz}/lib/liblzma.a \
        -DENABLE_TEST=OFF \
        -DENABLE_CPIO=OFF \
        -DENABLE_TAR=OFF \
        -DENABLE_CAT=OFF \
        -DENABLE_ACL=OFF \
        -DENABLE_XATTR=OFF \
        -DENABLE_OPENSSL=OFF \
        -DENABLE_LIBXML2=OFF \
        -DENABLE_EXPAT=OFF \
        -DENABLE_LZO=OFF \
        -DENABLE_LZ4=OFF \
        -DENABLE_LZMA=ON \
        -DENABLE_ZSTD=OFF \
        -DENABLE_BZip2=OFF \
        -DENABLE_ZLIB=ON
      cmake --build build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      cmake --install build
      runHook postInstall
    '';
  };

  emscriptenBrotli = pkgs.stdenvNoCC.mkDerivation {
    pname = "brotli-emscripten";
    inherit (pkgs.brotli) version src;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.emscripten
      pkgs.ninja
    ];
    dontUseCmakeConfigure = true;
    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache

      emcmake cmake -S . -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$out \
        -DBUILD_SHARED_LIBS=OFF \
        -DBROTLI_BUILD_TOOLS=OFF \
        -DBROTLI_DISABLE_TESTS=ON
      cmake --build build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      cmake --install build
      runHook postInstall
    '';
  };

  emscriptenBlake3 = pkgs.stdenvNoCC.mkDerivation {
    pname = "libblake3-emscripten";
    inherit (pkgs.libblake3) version src;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.emscripten
      pkgs.ninja
    ];
    dontUseCmakeConfigure = true;
    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache

      emcmake cmake -S c -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$out \
        -DBUILD_SHARED_LIBS=OFF \
        -DBLAKE3_SIMD_TYPE=none \
        -DBLAKE3_USE_TBB=OFF \
        -DBLAKE3_FETCH_TBB=OFF \
        -DBUILD_TESTING=OFF
      cmake --build build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      cmake --install build
      runHook postInstall
    '';
  };

  emscriptenLibgit2 = pkgs.stdenvNoCC.mkDerivation {
    pname = "libgit2-emscripten";
    inherit (pkgs.libgit2) version src;
    nativeBuildInputs = [
      pkgs.cmake
      pkgs.emscripten
      pkgs.ninja
    ];
    dontUseCmakeConfigure = true;
    postPatch = ''
      substituteInPlace src/util/integer.h \
        --replace-fail "# if (SIZE_MAX == UINT_MAX)" "# if !defined(__EMSCRIPTEN__) && (SIZE_MAX == UINT_MAX)"
    '';
    configurePhase = ''
      runHook preConfigure
      runHook postConfigure
    '';
    buildPhase = ''
      runHook preBuild
      HOME=$TMPDIR
      mkdir -p .emscriptencache
      export EM_CACHE=$(pwd)/.emscriptencache

      emcmake cmake -S . -B build -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DCMAKE_INSTALL_PREFIX=$out \
        -DCMAKE_PREFIX_PATH="${emscriptenZlib}" \
        -DBUILD_SHARED_LIBS=OFF \
        -DBUILD_TESTS=OFF \
        -DBUILD_CLI=OFF \
        -DBUILD_EXAMPLES=OFF \
        -DUSE_HTTPS=OFF \
        -DUSE_SSH=OFF \
        -DUSE_NTLMCLIENT=OFF \
        -DREGEX_BACKEND=builtin \
        -DZLIB_INCLUDE_DIR=${emscriptenZlib}/include \
        -DZLIB_LIBRARY=${emscriptenZlib}/lib/libz.a
      cmake --build build
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      cmake --install build
      runHook postInstall
    '';
  };

  emscriptenMesonLayer =
    finalAttrs: prevAttrs:
    {
      nativeBuildInputs = (prevAttrs.nativeBuildInputs or [ ]) ++ [
        pkgs.cmake
        pkgs.emscripten
        pkgs.meson
        pkgs.ninja
        pkgs.perl
        pkgs.pkg-config
      ];
      buildInputs = (prevAttrs.buildInputs or [ ]) ++ nativeDependencyProbeInputs;

      mesonFlags = (prevAttrs.mesonFlags or [ ]) ++ [
        "--cross-file=${emscriptenMesonCrossFile}"
        "-Ddefault_library=static"
        "-Db_staticpic=false"
        "-Db_lto=false"
      ]
      ++ pkgs.lib.optional ((prevAttrs.pname or "") == "nix-util") "-Dcpuid=disabled"
      ++ pkgs.lib.optional ((prevAttrs.pname or "") == "nix-expr") "-Dgc=disabled"
      ++ pkgs.lib.optionals ((prevAttrs.pname or "") == "nix-store") [
        "-Dseccomp-sandboxing=disabled"
        "-Ds3-aws-auth=disabled"
      ];

      preConfigure =
        (prevAttrs.preConfigure or "")
        + ''
          appendToVar mesonFlags "-Db_lto=false"
        ''
        + pkgs.lib.optionalString ((prevAttrs.pname or "") == "nix-util") ''
          appendToVar mesonFlags "-Dcpuid=disabled"
        ''
        + pkgs.lib.optionalString ((prevAttrs.pname or "") == "nix-expr") ''
          appendToVar mesonFlags "-Dgc=disabled"
        ''
        + pkgs.lib.optionalString ((prevAttrs.pname or "") == "nix-store") ''
          appendToVar mesonFlags "-Dseccomp-sandboxing=disabled"
          appendToVar mesonFlags "-Ds3-aws-auth=disabled"
        '';

      postPatch =
        (prevAttrs.postPatch or "")
        + ''
          while IFS= read -r mesonFile; do
            substituteInPlace "$mesonFile" \
              --replace-fail "prelink : true" "prelink : false"
          done < <(grep -rl "prelink : true" . || true)
          if [ -f args.cc ]; then
            substituteInPlace args.cc \
              --replace-fail "std::string(s.begin(), i)" "std::string(s.substr(0, i))"
          fi
          if [ -f hilite.cc ]; then
            sed -i '1a #include <algorithm>' hilite.cc
          fi
          if [ -f unix/file-system.cc ]; then
            perl -0pi -e 's|void setWriteTime\\(\\n    const std::filesystem::path & path, time_t accessedTime, time_t modificationTime, std::optional<bool> optIsSymlink\\)\\n\\{|void setWriteTime(\\n    const std::filesystem::path & path, time_t accessedTime, time_t modificationTime, std::optional<bool> optIsSymlink)\\n{\\n#ifdef __EMSCRIPTEN__\\n    (void) path;\\n    (void) accessedTime;\\n    (void) modificationTime;\\n    (void) optIsSymlink;\\n    return;\\n#endif\\n|s' unix/file-system.cc
            substituteInPlace unix/file-system.cc \
              --replace-fail "#if HAVE_UTIMENSAT && HAVE_DECL_AT_SYMLINK_NOFOLLOW" "#if !defined(__EMSCRIPTEN__) && HAVE_UTIMENSAT && HAVE_DECL_AT_SYMLINK_NOFOLLOW" \
              --replace-fail "#  if HAVE_LUTIMES" "#  if !defined(__EMSCRIPTEN__) && HAVE_LUTIMES"
          fi
          if [ -f posix-fs-canonicalise.cc ]; then
            substituteInPlace posix-fs-canonicalise.cc \
              --replace-fail "#ifndef _WIN32 // TODO implement" "#if !defined(_WIN32) && !defined(__EMSCRIPTEN__) // TODO implement"
          fi
          if [ -f include/nix/store/binary-cache-store.hh ]; then
            substituteInPlace include/nix/store/binary-cache-store.hh \
              --replace-fail "constexpr const static std::string realisationsPrefix" "inline const static std::string realisationsPrefix" \
              --replace-fail "constexpr const static std::string cacheInfoFile" "inline const static std::string cacheInfoFile"
          fi
          if [ -f http-binary-cache-store.cc ]; then
            substituteInPlace http-binary-cache-store.cc \
              --replace-fail "req.data = {sizeHint, source};" "req.data = {static_cast<size_t>(sizeHint), source};"
          fi
          if [ -f filetransfer.cc ]; then
            cp ${./emscripten-filetransfer.cc} filetransfer.cc
          fi
          if [ -f names.cc ]; then
            substituteInPlace names.cc \
              --replace-fail "return {s, size_t(p - s)};" "return {&*s, size_t(p - s)};"
          fi
          if [ -f serialise.cc ]; then
            substituteInPlace serialise.cc \
              --replace-fail "#include <boost/coroutine2/coroutine.hpp>" "" \
              --replace-fail "#include <boost/coroutine2/protected_fixedsize_stack.hpp>" ""
            # Emscripten cannot use Boost.Context fcontext. These adapters are only
            # needed as streaming bridges, so buffer them instead of using stackful
            # coroutines that require unavailable wasm context switching.
            perl -0pi -e 's|std::unique_ptr<FinishSink> sourceToSink\(fun<void\(Source &\)> reader\)\n\{.*?\n\}\n\nvoid writePadding|std::unique_ptr<FinishSink> sourceToSink(fun<void(Source &)> reader)\n{\n    struct SourceToSink : FinishSink\n    {\n        fun<void(Source &)> reader;\n        StringSink buffered;\n\n        SourceToSink(fun<void(Source &)> reader)\n            : reader(reader)\n        {\n        }\n\n        void operator()(std::string_view in) override\n        {\n            buffered(in);\n        }\n\n        void finish() override\n        {\n            StringSource source(buffered.s);\n            reader(source);\n        }\n    };\n\n    return std::make_unique<SourceToSink>(reader);\n}\n\nstd::unique_ptr<Source> sinkToSource(fun<void(Sink &)> writer, fun<void()> eof)\n{\n    struct BufferedGeneratedSource : Source\n    {\n        std::string buffered;\n        StringSource source;\n        fun<void()> eof;\n\n        BufferedGeneratedSource(std::string && data, fun<void()> eof)\n            : buffered(std::move(data))\n            , source(buffered)\n            , eof(eof)\n        {\n        }\n\n        size_t read(char * data, size_t len) override\n        {\n            try {\n                return source.read(data, len);\n            } catch (EndOfFile &) {\n                eof();\n                unreachable();\n            }\n        }\n    };\n\n    StringSink sink;\n    writer(sink);\n    return std::make_unique<BufferedGeneratedSource>(std::move(sink.s), eof);\n}\n\nvoid writePadding|s' serialise.cc
            if grep -q 'boost::coroutines2' serialise.cc; then
              echo 'Emscripten serialise.cc patch failed to remove Boost.Coroutine use' >&2
              grep -n 'boost::coroutines2\|coroutine<' serialise.cc >&2
              exit 1
            fi
          fi
          if [ -f primops.cc ]; then
            substituteInPlace primops.cc \
              --replace-fail "std::regex_match(str.begin(), str.end(), match, *regex)" "std::regex_match(str.data(), str.data() + str.size(), match, *regex)" \
              --replace-fail "std::cregex_iterator(str.begin(), str.end(), *regex)" "std::cregex_iterator(str.data(), str.data() + str.size(), *regex)"
          fi
          if [ -f meson.build ] && grep -q "toml11 = dependency" meson.build; then
            perl -0pi -e "s|toml11 = dependency\\(\\n  'toml11',\\n  version : '>=3\\.7\\.0',\\n  method : 'cmake',\\n  include_type : 'system',\\n\\)|toml11 = declare_dependency(\\n  compile_args : ['-isystem', '${pkgs.toml11}/include'],\\n  version : '4.4.0',\\n)|" meson.build
          fi
        '';

      doCheck = false;
      doInstallCheck = false;
      separateDebugInfo = false;
    };
in
(pkgs.nix.overrideAllMesonComponents emscriptenMesonLayer)
// {
  emscriptenDeps = {
    blake3 = emscriptenBlake3;
    boost = emscriptenBoost;
    brotli = emscriptenBrotli;
    libarchive = emscriptenLibarchive;
    libgit2 = emscriptenLibgit2;
    xz = emscriptenXz;
    zlib = emscriptenZlib;
  };
}
