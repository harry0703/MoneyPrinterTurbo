# HC20260810-002 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「吃饭快慢留个停顿」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `709db0dfaadbf78cc5e11132227b058ab4a11a65fee6e842f89b3fc5aa89f2ff`
- `A02.png`: `dbc96b95d627e2028535dbaed00a52b9184b89c3460dca92e6f62a5161677d84`
- `A03.png`: `6324dce22658b90fe233257b6752478486e0f9891bdfb7591286ac91b67ac768`
- `A04.png`: `52a12207ec0378af6c8ad3f5fd13bea5eb667d83bc20f66b7fd65ff3e83a1734`
- `A05.png`: `2d99601aa2a874efb943cf87e51fa60c1a5034a46def472e8cd5b2a25e6e1beb`
- `A06.png`: `79b6db0d05d141ede5d568f822518d4ba0ad802061c7581729371d648ef082d2`
- `A07.png`: `31d8ca0bc41c5f3953bf577d3e81a8c07ff5486d4188859e3925efd173ebd22c`
- `cover-v01.png`: `a17470179aa9cace360b7d7aad039b65aac8a7d314d8f0f063a95241330fdea6`
