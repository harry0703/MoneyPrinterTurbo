# MoneyPrinterTurbo 💸

只需提供一个视频 **主题** 或 **关键词** ，就可以全自动生成视频文案、视频素材、视频字幕、视频背景音乐，然后合成一个高清的短视频。

## 功能特性 🎯

- [x] 完整的 **MVC架构**，代码 **结构清晰**，易于维护，支持API和Web界面
- [x] 支持多种 **高清视频** 尺寸
    - [x] 竖屏 9:16，`1080x1920`
    - [x] 横屏 16:9，`1920x1080`
- [x] 支持 **中文** 和 **英文** 视频文案
- [x] 支持 **多种语音** 合成
- [x] 支持 **字幕生成**，可以调整字体、颜色、大小，同时支持字幕描边设置
- [x] 支持 **背景音乐**，随机或者指定音乐文件
- [x] 视频素材来源 **无版权** 问题

### 后期计划 🚀

- [ ] 完善异步API接口，进度显示
- [ ] 优化语音合成，利用大模型，使其合成的声音，更加自然，情绪更加丰富
- [ ] 增加视频转场效果，使其看起来更加的流畅
- [ ] 优化字幕效果
- [ ] 优化视频素材的匹配度

## 视频演示 📺

### 竖屏 9:16

▶️ 《如何增加生活的乐趣》

https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/a84d33d5-27a2-4aba-8fd0-9fb2bd91c6a6

▶️ 《生命的意义是什么》

https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/112c9564-d52b-4472-99ad-970b75f66476

### 横屏 16:9

▶️《生命的意义是什么》

https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/346ebb15-c55f-47a9-a653-114f08bb8073

▶️《为什么要运动》

https://github.com/harry0703/MoneyPrinterTurbo/assets/4928832/271f2fae-8283-44a0-8aa0-0ed8f9a6fa87

## 安装部署 📥

建议使用 [conda](https://conda.io/projects/conda/en/latest/user-guide/install/index.html) 创建 python 虚拟环境

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
conda create -n MoneyPrinterTurbo python=3.10
conda activate MoneyPrinterTurbo
pip install -r requirements.txt

cp config.example.toml config.toml
```

需要先配置 `config.toml` 中的参数

## 快速使用 🚀

完整的使用演示视频，可以查看：https://v.douyin.com/iFhnwsKY/

请先确认你按照 `config.toml` 文件中的说明，配置好了 `openai_api_key` 和 `pexels_api_keys`。否则项目无法正常运行。

### 启动Web界面

```shell
sh webui.sh
```

启动后，会自动打开浏览器，效果如下图：
![](docs/webui.jpg)

### 启动API服务

```shell
python main.py
```

启动后，可以查看 `API文档` http://127.0.0.1:8080/docs 直接在线调试接口，快速体验。
![](docs/api.jpg)

## 语音合成 🗣

所有支持的声音列表，可以查看：[声音列表](./docs/voice-list.txt)

## 字幕生成 📜

当前支持2种字幕生成方式：

- edge
- whisper

可以修改 `config.toml` 配置文件中的 `subtitle_provider` 进行切换，如果留空，表示不生成字幕。

## 背景音乐 🎵

用于视频的背景音乐，位于项目的 `resource/songs` 目录下。当前项目里面放了一些默认的音乐，来自于 YouTube 视频，如有侵权，请删除。

## 字幕字体 🅰

用于视频字幕的渲染，位于项目的 `resource/fonts` 目录下，你也可以放进去自己的字体。

## 反馈建议 📢

- 可以提交 [issue](https://github.com/harry0703/MoneyPrinterTurbo/issues)
  或者 [pull request](https://github.com/harry0703/MoneyPrinterTurbo/pulls)。
- 也可以关注我的 **抖音** 或 **视频号**：`网旭哈瑞.AI`
    - 我会在上面发布一些 **使用教程** 和 **纯技术** 分享。
    - 如果有更新和优化，我也会在上面 **及时通知**。
    - 有问题也可以在上面 **留言**，我会 **尽快回复**。

|                   抖音                    |              |                     视频号                     |
|:---------------------------------------:|:------------:|:-------------------------------------------:|
| <img src="docs/douyin.jpg" width="180"> |              | <img src="docs/shipinghao.jpg" width="200"> |

## 特别感谢 🙏

该项目基于 https://github.com/FujiwaraChoki/MoneyPrinter 重构而来，做了大量的优化，增加了更多的功能。
感谢原作者的开源精神。

## 许可证 📝

点击查看 [`LICENSE`](LICENSE) 文件

