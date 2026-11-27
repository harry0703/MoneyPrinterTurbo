# MoneyPrinterTurbo 桌面版

桌面版使用 Tauri 运行现有的 Streamlit 工作台。应用包内包含 Python、项目依赖、FFmpeg、ffprobe 和默认资源。

| 系统 | 发行包 | 启动方式 |
| --- | --- | --- |
| macOS 14 或更新版本，Apple Silicon | `MoneyPrinterTurbo-v<版本>-macos-arm64.zip` | 解压后打开 `MoneyPrinterTurbo.app`，也可将它移到「应用程序」。 |
| Windows x64 | `MoneyPrinterTurbo-v<版本>-windows-x64.zip` | 解压整个目录，双击 `MoneyPrinterTurbo.exe`。日常使用可用普通用户权限。 |
| Ubuntu 22.04 x64 | `MoneyPrinterTurbo-v<版本>-ubuntu-x64.zip` | 使用 `unzip` 解压后运行目录内的 `bin/mpt-desktop`。 |

- macOS 使用系统提供的 WKWebView。
- Windows 需要系统已有的 WebView2 Runtime。便携包已携带所需的 Visual C++ 运行库。
- Ubuntu 需要系统的 GTK 3 和 WebKitGTK 4.1 运行库。
- 云端功能需要网络和相应的 API Key。Whisper 模型权重可在首次使用时下载。Redis、Ollama 和 Kokoro 等服务仅在使用相应功能时需要。

## 窗口与存储

默认窗口为 1360 × 930 逻辑像素，可用空间较小时会自动缩小。视口宽度达到 1360 像素时显示四列。macOS 关闭窗口后可以从程序坞重新打开，使用 `⌘Q` 退出。Windows 关闭窗口时会提示确认退出。

视频成品、素材缓存和临时文件默认存放在「文档」下的 `MoneyPrinterTurbo/storage`。可在「设置 → 常规」打开或更改存储目录。更改在重启后生效，已有文件保留在原目录。应用设置和启动日志 `backend.log` 位于各平台的用户数据目录。开发测试可通过绝对路径 `MPT_HOME` 指定独立的数据目录。

## 从源码构建

从项目根目录执行命令。各平台都需要 uv 和 Rust 1.90 或更新版本。

### macOS

需要 Xcode 命令行工具、Tauri CLI 2 和可在 macOS 14 上运行的独立 arm64 `ffprobe`。构建使用 Python 锁文件中 `imageio-ffmpeg` 自带的 `ffmpeg`。

```sh
MPT_MEDIA_TOOLS_DIRECTORY=/path/to/ffprobe-bin sh desktop/build-macos.sh
```

应用生成在 `storage/desktop/target/release/bundle/macos/MoneyPrinterTurbo.app`。本机源码构建使用临时签名。

### Windows

需要 Rust 的 `x86_64-pc-windows-msvc` 目标、Visual Studio 的 x64 C++ 工具和可再发行运行库，以及包含 Windows x64 `ffmpeg.exe` 和 `ffprobe.exe` 的目录。在 Visual Studio 的 x64 开发者命令行下运行：

```powershell
powershell -File desktop/build-windows.ps1 -MediaToolsDirectory 'C:\ffmpeg\bin'
```

便携目录和 ZIP 生成在 `storage/desktop/windows-x64/dist/`，可用 `-OutputRoot` 指定目录。

### Ubuntu

需要 C 编译器、pkg-config、zip、GTK 3 和 WebKitGTK 4.1 开发库，以及可在 Ubuntu 22.04 上运行的独立 Linux x64 `ffprobe`。

```sh
MPT_MEDIA_TOOLS_DIRECTORY=/path/to/ffprobe-bin sh desktop/build-ubuntu.sh
```

归档生成在 `storage/desktop/ubuntu/`。

## 正式发布

- macOS 使用 Developer ID Application 签署应用和随包的原生代码，提交 Apple 公证。将公证票据附到 `.app` 后，再生成最终 ZIP。
- Windows 对最终的 `MoneyPrinterTurbo.exe` 做带时间戳的 Authenticode 签名，验签通过后再生成便携 ZIP。
- 为各平台最终下载文件生成 SHA-256 校验值。在目标系统上解压并启动发行包，确认工作台和随包媒体工具正常运行。
