## 常见问题 🤔

### ❓如何使用免费的OpenAI GPT-3.5模型?

[OpenAI宣布ChatGPT里面3.5已经免费了](https://openai.com/blog/start-using-chatgpt-instantly)，有开发者将其封装成了API，可以直接调用

**确保你安装和启动了docker服务**，执行以下命令启动docker服务

```shell
docker run -p 3040:3040 missuo/freegpt35
```

启动成功后，修改 `config.toml` 中的配置

- `llm_provider` 设置为 `openai`
- `openai_api_key` 随便填写一个即可，比如 '123456'
- `openai_base_url` 改为 `http://localhost:3040/v1/`
- `openai_model_name` 改为 `gpt-3.5-turbo`

### ❓AttributeError: 'str' object has no attribute 'choices'`

这个问题是由于 OpenAI 或者其他 LLM，没有返回正确的回复导致的。

大概率是网络原因， 使用 **VPN**，或者设置 `openai_base_url` 为你的代理 ，应该就可以解决了。

### ❓RuntimeError: No ffmpeg exe could be found

通常情况下，ffmpeg 会被自动下载，并且会被自动检测到。
但是如果你的环境有问题，无法自动下载，可能会遇到如下错误：

```
RuntimeError: No ffmpeg exe could be found.
Install ffmpeg on your system, or set the IMAGEIO_FFMPEG_EXE environment variable.
```

此时你可以从 https://www.gyan.dev/ffmpeg/builds/ 下载ffmpeg，解压后，设置 `ffmpeg_path` 为你的实际安装路径即可。

```toml
[app]
# 请根据你的实际路径设置，注意 Windows 路径分隔符为 \\
ffmpeg_path = "C:\\Users\\harry\\Downloads\\ffmpeg.exe"
```

### ❓生成音频时报错或下载视频报错

[issue 56](https://github.com/harry0703/MoneyPrinterTurbo/issues/56)

```
failed to generate audio, maybe the network is not available. 
if you are in China, please use a VPN.
```

[issue 44](https://github.com/harry0703/MoneyPrinterTurbo/issues/44)

```
failed to download videos, maybe the network is not available. 
if you are in China, please use a VPN.
```

这个大概率是网络原因，无法访问境外的服务，请使用VPN解决。

### ❓ImageMagick is not installed on your computer

[issue 33](https://github.com/harry0703/MoneyPrinterTurbo/issues/33)

1. 按照 `示例配置` 里面提供的 `下载地址`
   ，安装 https://imagemagick.org/archive/binaries/ImageMagick-7.1.1-29-Q16-x64-static.exe, 用静态库
2. 不要安装在中文路径里面，避免出现一些无法预料的问题

[issue 54](https://github.com/harry0703/MoneyPrinterTurbo/issues/54#issuecomment-2017842022)

如果是linux系统，可以手动安装，参考 https://cn.linux-console.net/?p=16978

感谢 [@wangwenqiao666](https://github.com/wangwenqiao666)的研究探索

### ❓ImageMagick的安全策略阻止了与临时文件@/tmp/tmpur5hyyto.txt相关的操作

[issue 92](https://github.com/harry0703/MoneyPrinterTurbo/issues/92)

可以在ImageMagick的配置文件policy.xml中找到这些策略。
这个文件通常位于 /etc/ImageMagick-`X`/ 或 ImageMagick 安装目录的类似位置。
修改包含`pattern="@"`的条目，将`rights="none"`更改为`rights="read|write"`以允许对文件的读写操作。

感谢 [@chenhengzh](https://github.com/chenhengzh)的研究探索

### ❓OSError: [Errno 24] Too many open files

[issue 100](https://github.com/harry0703/MoneyPrinterTurbo/issues/100)

这个问题是由于系统打开文件数限制导致的，可以通过修改系统的文件打开数限制来解决。

查看当前限制

```shell
ulimit -n
```

如果过低，可以调高一些，比如

```shell
ulimit -n 10240
```

### ❓AttributeError: module 'PIL.Image' has no attribute 'ANTIALIAS'

[issue 101](https://github.com/harry0703/MoneyPrinterTurbo/issues/101),
[issue 83](https://github.com/harry0703/MoneyPrinterTurbo/issues/83),
[issue 70](https://github.com/harry0703/MoneyPrinterTurbo/issues/70)

先看下当前的 Pillow 版本是多少

```shell
pip list |grep Pillow
```

如果是 10.x 的版本，可以尝试下降级看看，有用户反馈降级后正常

```shell
pip uninstall Pillow
pip install Pillow==9.5.0
# 或者降级到 8.4.0
pip install Pillow==8.4.0
```