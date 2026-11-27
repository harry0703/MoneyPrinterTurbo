#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Linux ] || [ "$(uname -m)" != x86_64 ]; then
    echo "请在 x86_64 Ubuntu 上构建。" >&2
    exit 1
fi

media_dir="${MPT_MEDIA_TOOLS_DIRECTORY:-}"
if [ -z "$media_dir" ] || [ ! -x "$media_dir/ffprobe" ]; then
    echo "请通过 MPT_MEDIA_TOOLS_DIRECTORY 提供 Linux x86_64 的 ffprobe。" >&2
    exit 2
fi
"$media_dir/ffprobe" -version >/dev/null

build_dir="$PWD/storage/desktop/ubuntu"
export UV_NO_REGISTRY=1
export UV_PROJECT_ENVIRONMENT="$build_dir/venv"
export CARGO_TARGET_DIR="$build_dir/target"
mkdir -p "$build_dir"

uv sync --frozen --no-dev --no-editable --reinstall-package mpt --managed-python --python 3.11
venv_python="$UV_PROJECT_ENVIRONMENT/bin/python"
runtime="$("$venv_python" -c 'import sys; print(sys.base_prefix)')"
packages="$("$venv_python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
version="$("$venv_python" -c 'from importlib.metadata import version; print(version("mpt"))')"
ffmpeg="$(env -u IMAGEIO_FFMPEG_EXE "$venv_python" -c 'from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())')"
cargo build --locked --release --manifest-path desktop/src-tauri/Cargo.toml

staging="$(mktemp -d "$build_dir/package.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
name="MoneyPrinterTurbo"
bundle="$staging/$name"
# Tauri 在 Linux 上从可执行文件旁的 ../lib/<产品名> 解析资源目录。
resources="$bundle/lib/$name"
site="$resources/python/lib/python3.11/site-packages"
mkdir -p "$bundle/bin" "$site" "$resources/tools"
cp -a "$runtime/." "$resources/python/"
cp -a "$packages/." "$site/"
install -m 755 "$CARGO_TARGET_DIR/release/mpt-desktop" "$bundle/bin/mpt-desktop"
install -m 644 desktop/backend.py "$resources/backend.py"
install -m 755 "$ffmpeg" "$resources/tools/ffmpeg"
install -m 755 "$media_dir/ffprobe" "$resources/tools/ffprobe"
if [ -f "$media_dir/LICENSE" ]; then
    install -m 644 "$media_dir/LICENSE" "$resources/tools/FFmpeg-LICENSE.txt"
fi
find "$site" -path '*/mpt-*.dist-info/direct_url.json' -delete

archive="MoneyPrinterTurbo-v$version-ubuntu-x64.zip"
# ZIP 中保留运行时符号链接和可执行权限。
(cd "$staging" && zip -qry "$archive" "$name" -x '*.pyc' '*/__pycache__/*')
mv -f "$staging/$archive" "$build_dir/$archive"
printf '%s\n' "$build_dir/$archive"
