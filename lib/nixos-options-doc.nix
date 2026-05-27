# Vendored from upstream Nixpkgs' nixos/lib/make-options-doc/default.nix.
# This app only needs the pure optionsNix renderer, so the derivation-backed
# CommonMark/AsciiDoc/JSON renderers are intentionally omitted.
{
  lib,
  options,
  transformOptions ? lib.id,
  warningsAreErrors ? true,
  ...
}:

let
  rawOpts = lib.optionAttrSetToDocList options;
  transformedOpts = map transformOptions rawOpts;
  filteredOpts = lib.filter (opt: opt.visible && !opt.internal) transformedOpts;

  genRelatedPackages =
    packages: _optName:
    let
      unpack =
        p:
        if lib.isString p then
          { name = p; }
        else if lib.isList p then
          { path = p; }
        else
          p;
      describe =
        args:
        let
          title = args.title or null;
          name = args.name or (lib.concatStringsSep "." args.path);
        in
        ''
          - [${lib.optionalString (title != null) "${title} aka "}`pkgs.${name}`](
              https://search.nixos.org/packages?show=${name}&sort=relevance&query=${name}
            )${lib.optionalString (args ? comment) "\n\n  ${args.comment}"}
        '';
    in
    lib.concatMapStrings (p: describe (unpack p)) packages;

  optionsList = lib.flip map filteredOpts (
    opt:
    opt
    // lib.optionalAttrs (opt ? relatedPackages && opt.relatedPackages != [ ]) {
      relatedPackages = genRelatedPackages opt.relatedPackages opt.name;
    }
  );

  optionsNix = builtins.listToAttrs (
    map (o: {
      inherit (o) name;
      value = removeAttrs o [
        "name"
        "visible"
        "internal"
      ];
    }) optionsList
  );
in
{
  inherit optionsNix warningsAreErrors;
}
