# MoneyPrinterTurbo — Official Python Package

**mpt is the official Python distribution of
[MoneyPrinterTurbo](https://github.com/harry0703/MoneyPrinterTurbo), maintained by
[harry0703](https://pypi.org/user/harry0703/).**

Install the official package with **`python -m pip install mpt`**.
The separately named `MoneyPrinterTurbo` package on PyPI is a third-party
distribution and is not maintained by this project.

MoneyPrinterTurbo generates short videos from a topic or a prepared script.
It combines local or online materials, voice narration, subtitles, and background
music. Use the WebUI interactively or run the same video pipeline from the CLI.

## Install

Requires Python 3.11 or later. A virtual environment is recommended:

```sh
python -m venv .venv
# macOS / Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install mpt
```

## Start the WebUI

```sh
mpt webui
```

The WebUI listens on localhost and opens in your browser. To select a port or run
without opening a browser:

```sh
mpt webui --port 8503 --headless
```

## Generate a video from the CLI

```sh
mpt cli --help
mpt cli --video-script "Your complete script." \
  --video-source local --video-materials /absolute/path/clip.mp4 \
  --custom-audio-file /absolute/path/narration.wav \
  --no-subtitle-enabled --bgm-type none
```

Local images and videos are supported. Online language models, stock media,
and speech providers require the appropriate configuration and network access.
Choose providers and enter credentials in the WebUI settings or `config.toml`.

The package includes default fonts, background music, and an FFmpeg binary through
imageio-ffmpeg. An installed system FFmpeg takes precedence. Whisper models are
loaded on demand.

## Configuration and generated files

The installed application keeps configuration, credentials, uploads, and generated
videos in your user directory:

| System | Default directory |
| --- | --- |
| macOS | `~/Library/Application Support/MoneyPrinterTurbo` |
| Windows | `%LOCALAPPDATA%\MoneyPrinterTurbo` |
| Linux | `~/.local/share/MoneyPrinterTurbo` (or `$XDG_DATA_HOME/MoneyPrinterTurbo`) |

Set `MPT_HOME` before starting the application to choose another directory.
Configuration is stored in `config.toml`; generated videos are under
`storage/tasks/<task-id>/`. Existing user configuration and resources are preserved
when the application starts or upgrades.

See the [project documentation](https://github.com/harry0703/MoneyPrinterTurbo)
for supported providers and advanced options. Report problems through
[GitHub Issues](https://github.com/harry0703/MoneyPrinterTurbo/issues).
