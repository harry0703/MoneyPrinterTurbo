#!/usr/bin/env bash
# 影创AI 桌面端 - macOS 本地打包脚本（x86_64 / arm64 均可）
set -euo pipefail

# 用法:
#   ./scripts/bundle-macos.sh            # 使用当前后端 dist 打包成 .app + .dmg
#   MPT_ARCH=arm64 ./scripts/bundle-macos.sh
#
# 步骤:
#   1) 构建 Tauri 壳（一次构建出 .app）
#   2) 把 PyInstaller 后端 dist/mpt-backend 注入 .app/Contents/Resources/backend-<ARCH>/
#   3) 由注入后的 .app 重新生成 .dmg（避免再次 tauri build 覆盖注入结果）

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DESKTOP_DIR="$PROJECT_ROOT/desktop"
BACKEND_DIST="$DESKTOP_DIR/backend/dist/mpt-backend"

# 目标架构：默认当前机器架构 (x86_64 / aarch64)
ARCH="${MPT_ARCH:-$(uname -m)}"
[ "$ARCH" = "arm64" ] && BACKEND_DIR="backend-aarch64" || BACKEND_DIR="backend-x86_64"

echo "==> [1/4] 构建 Tauri 壳 (target: $ARCH)"
cd "$DESKTOP_DIR"
npm install
npm run tauri build

# 找到构建产物 .app
APP_PATH=""
for cand in \
  "$DESKTOP_DIR/src-tauri/target/${ARCH}-apple-darwin/release/bundle/macos/YingChuangAI.app" \
  "$DESKTOP_DIR/src-tauri/target/release/bundle/macos/YingChuangAI.app"; do
  if [ -d "$cand" ]; then APP_PATH="$cand"; break; fi
done
if [ -z "$APP_PATH" ]; then
  echo "ERROR: 未找到构建产物 YingChuangAI.app" >&2
  exit 1
fi
echo "==> [2/4] 找到 .app: $APP_PATH"

echo "==> [3/4] 注入后端 -> $APP_PATH/Contents/Resources/$BACKEND_DIR"
if [ ! -d "$BACKEND_DIST" ]; then
  echo "ERROR: 后端产物不存在: $BACKEND_DIST (请先构建 PyInstaller)" >&2
  exit 1
fi
TARGET_RES="$APP_PATH/Contents/Resources/$BACKEND_DIR"
rm -rf "$TARGET_RES"
mkdir -p "$TARGET_RES"
cp -R "$BACKEND_DIST/." "$TARGET_RES/"

echo "==> [4/4] 由注入后的 .app 生成 DMG"
# tauri 已在此前 build 产出过 dmg 模板，这里直接对注入后的 .app 重新打包，
# 防止再次 tauri build 覆盖注入的后端。
DMG_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle/dmg"
mkdir -p "$DMG_DIR"
DMG_NAME="YingChuangAI_${ARCH}.dmg"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg \
    --volname "影创AI" \
    --app-drop-link 250 500 \
    --window-size 300 500 \
    "$DMG_DIR/$DMG_NAME" \
    "$APP_PATH"
  echo "✅ 完成。DMG: $DMG_DIR/$DMG_NAME"
else
  # create-dmg 未安装时用系统自带 hdiutil 生成只读压缩 DMG，
  # 效果等价：内含 .app + Applications 软链，无网络依赖。
  STAGING="$(mktemp -d)"
  cp -R "$APP_PATH" "$STAGING/"
  ln -s /Applications "$STAGING/Applications"
  hdiutil create \
    -volname "影创AI" \
    -srcfolder "$STAGING" \
    -ov -format UDZO "$DMG_DIR/$DMG_NAME"
  rm -rf "$STAGING"
  echo "✅ 完成（hdiutil）。DMG: $DMG_DIR/$DMG_NAME"
fi

echo ""
echo "✅ 完成。.app: $APP_PATH"
find "$DESKTOP_DIR/src-tauri/target" -name "*.dmg" -not -path "*debug*" | head -1
