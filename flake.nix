{
  description = "Terminal UI for browsing and playing media from Plex";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs =
    { self, nixpkgs }:
    let
      systems = [
        "aarch64-linux"
        "x86_64-linux"
      ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
    in
    {
      packages = forAllSystems (
        system:
        let
          pkgs = import nixpkgs { inherit system; };
        in
        rec {
          plex-tui = pkgs.python3Packages.buildPythonApplication {
            pname = "plex-tui";
            inherit version;
            pyproject = true;
            __structuredAttrs = true;

            src = self;

            nativeBuildInputs = [ pkgs.makeWrapper ];
            build-system = [ pkgs.python3Packages.hatchling ];
            dependencies = with pkgs.python3Packages; [
              pillow
              platformdirs
              plexapi
              textual
            ];
            nativeCheckInputs = [ pkgs.versionCheckHook ];
            pythonImportsCheck = [ "plextui" ];

            postFixup = ''
              wrapProgram $out/bin/plex-tui \
                --prefix PATH : ${pkgs.lib.makeBinPath [ pkgs.mpv ]}
            '';

            meta = {
              description = "Terminal UI for browsing and playing media from Plex";
              homepage = "https://github.com/so1omon563/plex-tui";
              license = pkgs.lib.licenses.mit;
              mainProgram = "plex-tui";
            };
          };

          default = plex-tui;
        }
      );
    };
}
