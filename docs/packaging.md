# pip Package and PyPI Release

The distribution package is named `mpt`, while the project name remains MoneyPrinterTurbo. The current source version is `1.3.10`,
published to [PyPI](https://pypi.org/project/mpt/1.3.10/) with both a wheel and an sdist.
Published files can't be overwritten, so later code changes require bumping the version before rebuilding and verifying.

## Build and Install

Requires Python 3.11 or newer. Dependencies are resolved and installed with the wheel; FFmpeg prefers the system
version, and the binary provided by imageio-ffmpeg can also be used.

Install from PyPI and launch:

```sh
python -m pip install mpt
mpt webui
mpt cli --help
```

Build and verify locally:

```sh
uv build --out-dir storage/package/mpt-dist
python -m pip install ./storage/package/mpt-dist/mpt-1.3.10-py3-none-any.whl
mpt --help
mpt webui
mpt cli --help
```

Before the official upload, confirm the PyPI account, target version and distribution hashes, avoiding batch uploads from a directory
mixed with old packages. Every release requires explicit authorization from the user and is never published automatically with commits or pushes.

## Pre-release Checks

```sh
uvx twine check --strict \
  storage/package/mpt-dist/mpt-1.3.10-py3-none-any.whl \
  storage/package/mpt-dist/mpt-1.3.10.tar.gz
```

Check the PyPI description page, distribution metadata and dependency installability, and complete a video generation in a fresh virtual environment.
Only run the official release after the upload is explicitly authorized; account passwords, verification codes and API tokens never go into the repository,
command examples or logs. The README in each language provides the user install entry point, while the PyPI description is maintained separately in
`docs/pypi-description.md`; updating repository docs doesn't automatically change the already published PyPI page.

`mpt webui` listens only on `127.0.0.1` by default, picks a free port starting from 8501, and opens the browser automatically.
Use `--host` and `--port` to set the address, and `--headless` to stop the browser from opening automatically:

```sh
mpt webui --port 8503 --headless
```

The CLI reuses the arguments, task pipeline, exit codes and JSON output of `python cli.py`. A complete offline example:

```sh
mpt cli --video-script "A short video from local materials." \
  --video-source local --video-materials /absolute/path/clip.mp4 \
  --custom-audio-file /absolute/path/narration.wav \
  --no-subtitle-enabled --bgm-type none
```

Online script, material, TTS and similar features still need the relevant service config, keys and network access. Whisper models are loaded
on demand and aren't included in the wheel. CLI logs go to stderr; on success stdout prints JSON containing the video path.

## Config and Data

Running from source keeps using the project root. The installed version doesn't depend on the current working directory; the default runtime directory is:

| Platform | Runtime directory |
| --- | --- |
| macOS | `~/Library/Application Support/MoneyPrinterTurbo` |
| Windows | `%LOCALAPPDATA%\MoneyPrinterTurbo` |
| Linux | `$XDG_DATA_HOME/MoneyPrinterTurbo`, default `~/.local/share/MoneyPrinterTurbo` |

The runtime directory can be set explicitly with `MPT_HOME` (also supported by the source version). In it:

- `config.toml`: initialized from a key-free template on first run; later starts never overwrite the existing config.
- `storage/tasks`: tasks and generated videos; other caches and uploads live under `storage`.
- `resource/fonts`, `resource/songs`: built-in resources are copied on first use, and you can add your own files.
- `models`: manually downloaded Whisper models can be placed here.

User resources only have missing files filled in, and upgrades never overwrite existing files. The package includes two default Chinese fonts,
a Vietnamese font and built-in background music; the alternate `STHeitiLight.ttc` and `MicrosoftYaHeiNormal.ttc`
are left out of the distribution to keep its size down. If you need these weights, put them in `resource/fonts` in the runtime directory.
The source version's original resources and appearance are unchanged.

## Local Verification Requirements

Rebuild the wheel from the sdist, install it into a fresh virtual environment that doesn't inherit system packages, leave the source directory and clear
`PYTHONPATH`, then verify `mpt cli --help`, the actual WebUI page and video generation. The output video should be
fully decodable by FFmpeg, and confirm that config and outputs aren't written into site-packages. The distribution must not include
the local `config.toml`, keys, caches, task outputs or local collaboration instructions.
