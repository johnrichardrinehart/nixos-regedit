{ pkgs, ... }:
{
  projectRootFile = "flake.nix";

  programs = {
    clang-format.enable = true;
    nixfmt.enable = true;
    prettier = {
      enable = true;
      settings = {
        printWidth = 100;
      };
    };
    ruff-format = {
      enable = true;
      lineLength = 100;
    };
    taplo.enable = true;
  };

  settings.formatter = {
    clang-format.includes = [
      "*.c"
      "*.cc"
    ];
    prettier.includes = [
      "*.css"
      "*.html"
      "*.js"
      "*.json"
      "*.md"
      "*.yaml"
      "*.yml"
    ];
    opentofu = {
      command = "${pkgs.opentofu}/bin/tofu";
      options = [ "fmt" ];
      includes = [ "*.tf" ];
    };
  };
}
