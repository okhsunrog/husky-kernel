{
  description = "Host tools for building the Pixel 8 Pro kernel";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/02c087f3fe673c9e317f206a627cb6b910336dbe";

  outputs = { nixpkgs, ... }:
    let
      system = "x86_64-linux";
      pkgs = nixpkgs.legacyPackages.${system};
    in
    {
      devShells.${system}.default = pkgs.mkShellNoCC {
        packages = with pkgs; [
          android-tools
          gitMinimal
          git-repo
          gnumake
          jdk21
          lz4
          patch
          python312
          unzip
          uv
          zip
        ];

        JAVA_HOME = "${pkgs.jdk21.home}";
        UV_PYTHON_DOWNLOADS = "never";
      };
    };
}
