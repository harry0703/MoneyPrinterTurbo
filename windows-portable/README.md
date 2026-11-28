# Windows portable prerequisite helper

This folder contains a proposed setup/update entry point for the extracted Windows portable release. It is not part of the source checkout's existing `webui.bat` launcher.

## Portable layout

Copy these three files to the **outer directory** of an extracted portable release, next to `start.bat`, `MoneyPrinterTurbo/`, and `lib/`:

- `Setup-And-Start.ps1` checks prerequisites and starts the WebUI.
- `Setup-And-Start.bat` launches the PowerShell helper.
- `update.bat` runs the checks and updates a Git checkout if one exists.

The release packaging process should copy these files to that outer directory. This repository does not currently contain its portable release packaging scripts.

## Behavior

The helper prefers the bundled Python and FFmpeg, then an existing local installation. If absent, it uses Windows Package Manager (`winget`) to install Python 3.11 or Gyan.FFmpeg. It installs missing Python dependencies from `requirements.txt`, records the working FFmpeg executable in `MoneyPrinterTurbo/config.toml` (backing up changed configuration), and launches Streamlit.

In update mode, it performs `git pull --ff-only` for a Git checkout and refreshes Python dependencies. An extracted archive without `.git` has no Git source update; the updater still checks its requirements. Source release updates must be installed separately in that case.

## Verification

The portable Windows 1.3.7 layout was exercised manually with bundled Python/FFmpeg available: the update check completed, WebUI launched, and a video was generated. Automatic installation through winget and the missing dependency paths have not been independently exercised. CI runs Windows smoke tests for the application, but currently does not package a portable release.
