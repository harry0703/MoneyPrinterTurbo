{
  description = "MoneyPrinterOmni - dev shell and launcher (Python deps are managed by uv.lock)";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = f: nixpkgs.lib.genAttrs systems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs:
        let
          python = pkgs.python311; # .python-version = 3.11, requires-python >= 3.11

          # Shared libraries needed by the manylinux wheels pulled in by uv
          # (av, azure-cognitiveservices-speech, onnxruntime, numpy, ...).
          runtimeLibs = with pkgs; [
            stdenv.cc.cc.lib
            zlib
            openssl
            libffi
            ffmpeg
          ];
        in
        {
          default = pkgs.mkShell {
            packages = [
              python
              pkgs.uv
              pkgs.ffmpeg # moviepy / bgm validation; imageio-ffmpeg also bundles one
              pkgs.imagemagick # optional text rendering fallback for moviepy
              pkgs.git
            ];

            env = {
              UV_PYTHON = "${python}/bin/python";
              UV_PYTHON_DOWNLOADS = "never";
            };

            shellHook = ''
              export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
              export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath runtimeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
              [ -f config.toml ] || echo "hint: cp config.example.toml config.toml"
              echo "run: uv sync --frozen && ./webui.sh   (add --extra twelvelabs if needed)"
            '';
          };
        });

      # `nix run` -> sync deps with uv, then start the WebUI.
      apps = forAllSystems (pkgs:
        let
          python = pkgs.python311;
          runtimeLibs = with pkgs; [ stdenv.cc.cc.lib zlib openssl libffi ffmpeg ];
          launcher = pkgs.writeShellScript "mpt-webui" ''
            export PATH="${pkgs.lib.makeBinPath [ python pkgs.uv pkgs.ffmpeg pkgs.imagemagick ]}:$PATH"
            export UV_PYTHON="${python}/bin/python"
            export UV_PYTHON_DOWNLOADS=never
            export LD_LIBRARY_PATH="${pkgs.lib.makeLibraryPath runtimeLibs}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            uv sync --frozen || exit 1
            exec sh ./webui.sh "$@"
          '';
        in
        {
          default = {
            type = "app";
            program = "${launcher}";
          };
        });
    };
}
