#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
if [ "$(uname -s)" != Darwin ] || [ "$(uname -m)" != arm64 ]; then
    echo "请在 Apple Silicon Mac 上构建。" >&2
    exit 1
fi

case "${1:-}" in
    ""|--dmg) ;;
    *) echo "用法 $0 [--dmg]" >&2; exit 2 ;;
esac

media_dir="${MPT_MEDIA_TOOLS_DIRECTORY:-}"
if [ -z "$media_dir" ] || [ ! -x "$media_dir/ffprobe" ]; then
    echo "请通过 MPT_MEDIA_TOOLS_DIRECTORY 提供 macOS arm64 的 ffprobe。" >&2
    exit 2
fi
lipo "$media_dir/ffprobe" -verify_arch arm64
# 拒绝依赖构建机 Homebrew 或其他外部动态库的二进制。
probe_libraries="$(otool -L "$media_dir/ffprobe")"
if printf '%s\n' "$probe_libraries" | awk 'NR > 1 && $1 !~ /^\/(usr\/lib|System\/Library)\// { invalid = 1 } END { exit !invalid }'; then
    echo "ffprobe 依赖包外动态库，请提供独立二进制。" >&2
    exit 2
fi

if [ -z "${CARGO:-}" ] && command -v rustup >/dev/null && toolchain_cargo="$(rustup which cargo 2>/dev/null)"; then
    export PATH="${toolchain_cargo%/*}:$PATH"
fi

build_dir="$PWD/storage/desktop"
python_version=3.11.17
export UV_PYTHON_INSTALL_DIR="$build_dir/managed-python"
export UV_PROJECT_ENVIRONMENT="$build_dir/build-venv"
export CARGO_TARGET_DIR="$build_dir/target"
mkdir -p "$build_dir"

uv python install "$python_version" --no-bin
uv sync --frozen --no-dev --no-editable --reinstall-package mpt --managed-python --python "$python_version"
venv_python="$UV_PROJECT_ENVIRONMENT/bin/python"
runtime="$("$venv_python" -c 'import sys; print(sys.base_prefix)')"
packages="$("$venv_python" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
ffmpeg="$(env -u IMAGEIO_FFMPEG_EXE "$venv_python" -c 'from imageio_ffmpeg import get_ffmpeg_exe; print(get_ffmpeg_exe())')"

(
    cd desktop
    cargo tauri build --bundles app --no-sign --ci
)

app="$CARGO_TARGET_DIR/release/bundle/macos/MoneyPrinterTurbo.app"
resources="$app/Contents/Resources"
# 保留 Python 发行版中的符号链接和可执行权限。业务代码来自已安装的 wheel。
ditto "$runtime" "$resources/python"
ditto "$packages" "$resources/python/lib/python3.11/site-packages"
install -m 644 desktop/backend.py "$resources/backend.py"
mkdir -p "$resources/tools"
install -m 755 "$ffmpeg" "$resources/tools/ffmpeg"
install -m 755 "$media_dir/ffprobe" "$resources/tools/ffprobe"
if [ -f "$media_dir/LICENSE" ]; then
    install -m 644 "$media_dir/LICENSE" "$resources/tools/FFmpeg-LICENSE.txt"
fi
find "$resources/python" -type f -name '*.pyc' -delete
# 去除本地安装元数据中的源码路径。
find "$resources/python/lib/python3.11/site-packages" -path '*/mpt-*.dist-info/direct_url.json' -delete

codesign --force --sign - "$resources/tools/ffmpeg" "$resources/tools/ffprobe"
codesign --force --sign - "$app"
codesign --verify --deep --strict "$app"
printf '%s\n' "$app"

if [ "${1:-}" = --dmg ]; then
    staging="$(mktemp -d "$build_dir/dmg.XXXXXX")"
    trap 'rm -rf "$staging"' EXIT
    ditto "$app" "$staging/MoneyPrinterTurbo.app"
    ln -s /Applications "$staging/Applications"
    dmg="$build_dir/MoneyPrinterTurbo-macos-arm64.dmg"
    hdiutil create -ov -format UDZO -volname 'MoneyPrinterTurbo' -srcfolder "$staging" "$dmg"
    printf '%s\n' "$dmg"
fi
