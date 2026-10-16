# pip 安装包与 PyPI 发布

发行包名采用 `mpt`，项目名称仍为 MoneyPrinterTurbo，版本沿用 `1.3.8`。
2026-10-16 已使用 `harry0703` 发布到
[PyPI](https://pypi.org/project/mpt/1.3.8/)，同时提供 wheel 和 sdist。
已发布文件不可覆盖，后续代码变更需要提升版本后重新构建和验证。

## 构建和安装

需要 Python 3.11 或更新版本。依赖会随 wheel 一起解析安装，FFmpeg 优先使用系统
版本，也可使用 imageio-ffmpeg 提供的二进制。

用户从 PyPI 安装并启动：

```sh
python -m pip install mpt
mpt webui
mpt cli --help
```

本地构建和验证：

```sh
uv build --out-dir storage/package/mpt-dist
python -m pip install ./storage/package/mpt-dist/mpt-1.3.8-py3-none-any.whl
mpt --help
mpt webui
mpt cli --help
```

正式上传前应确认 PyPI 账号、目标版本和发行包哈希，避免使用混有旧包的目录
进行批量上传。每次发布均需用户明确授权，不随代码提交或推送自动发布。

## 发布前检查

```sh
uvx twine check --strict \
  storage/package/mpt-dist/mpt-1.3.8-py3-none-any.whl \
  storage/package/mpt-dist/mpt-1.3.8.tar.gz
```

检查 PyPI 说明页、发行包元数据和依赖可安装性，并在新虚拟环境中完成视频生成。
只有明确授权上传后才执行正式发布；账号密码、验证码和 API Token 不写入仓库、
命令示例或日志。各语种 README 提供用户安装入口，PyPI 的说明单独维护在
`docs/pypi-description.md`；更新仓库文档不会自动修改已经发布的 PyPI 介绍页。

`mpt webui` 默认仅监听 `127.0.0.1`，从 8501 开始选择空闲端口，自动打开浏览器。
可使用 `--host`、`--port` 指定地址，`--headless` 禁止自动打开浏览器：

```sh
mpt webui --port 8503 --headless
```

CLI 复用 `python cli.py` 的参数、任务流水线、退出码和 JSON 输出。完整离线示例：

```sh
mpt cli --video-script "A short video from local materials." \
  --video-source local --video-materials /absolute/path/clip.mp4 \
  --custom-audio-file /absolute/path/narration.wav \
  --no-subtitle-enabled --bgm-type none
```

在线文案、素材、TTS 等功能仍需相应服务的配置、密钥和网络连接。Whisper 模型按需
加载，不放入 wheel。CLI 日志写入 stderr，成功时 stdout 输出包含视频路径的 JSON。

## 配置与数据

源码运行继续使用项目根目录。安装版不依赖当前工作目录，默认运行目录为：

| 平台 | 运行目录 |
| --- | --- |
| macOS | `~/Library/Application Support/MoneyPrinterTurbo` |
| Windows | `%LOCALAPPDATA%\MoneyPrinterTurbo` |
| Linux | `$XDG_DATA_HOME/MoneyPrinterTurbo`，默认 `~/.local/share/MoneyPrinterTurbo` |

可通过 `MPT_HOME` 显式指定运行目录（源码版也支持）。其中：

- `config.toml`：首次运行从不含密钥的模板初始化，后续启动不会覆盖已有配置。
- `storage/tasks`：任务和生成的视频；其他缓存和上传文件在 `storage` 下。
- `resource/fonts`、`resource/songs`：首次使用时复制内置资源，可添加自己的文件。
- `models`：可放置手工下载的 Whisper 模型。

用户资源只补齐缺失文件，升级不覆盖已有文件。安装包包含两种默认中文字体、
越南语字体和内置背景音乐；备用的 `STHeitiLight.ttc`、`MicrosoftYaHeiNormal.ttc`
不进入发行包，以控制文件体积。需要这些字重时可放入运行目录的 `resource/fonts`。
源码版原有资源和外观不变。

## 本地验证要求

从 sdist 重建 wheel，安装到不继承系统包的新虚拟环境，离开源码目录并清除
`PYTHONPATH` 后验证 `mpt cli --help`、WebUI 实际页面和视频生成。输出视频应由
FFmpeg 完整解码，并确认配置与产物没有写入 site-packages。发行包不得包含
本机 `config.toml`、密钥、缓存、任务产物或本地协作指令。
