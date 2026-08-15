# HC20260810-009 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「难任务换个时点比」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `89a8d7826813601a52040a72064e63dab6fd799f700ee35f4f498d1553873603`
- `A02.png`: `2203a82a4d5a3ca5873281584f2eda3a0584a86096b1dc51b4dbb8a86eeb6848`
- `A03.png`: `6fa4aedc1e961de9171541136e8482313f30ff0a1507c05fc3c27c4f9ed30373`
- `A04.png`: `debef681868a80f0db902702923dc688137579a94447b8266bd6cfaca441be84`
- `A05.png`: `48d658974c4cb0841d21a28cedc75250bc0557f1b8c274ca3f01f55bdcb5cda4`
- `A06.png`: `38116f69440f913ad1f35eb2b44760d235f7805525e685b5bd7c956c86dd8341`
- `A07.png`: `b73a52f4a92cb1a5b6aa07f9baa3d64d612a0a9d2fbddcaf7e346f86e402c254`
- `cover-v01.png`: `9162a9115c4fb4e42d8af0d304dc6752673e4c6ee88478517c3134b3c165e711`
