# HC20260810-007 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「咖啡先记饮用时点」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `85bb2ed8a21e106dcac0c98f0d475076ac3f4c4c8ca2c47858c475b058f39115`
- `A02.png`: `cf7d31069f292addbbb080a6a44799b76e0297897c5bfae4c57d3280390e0731`
- `A03.png`: `9499456c349a2f24106653646d1624d68a99542e361a0da524ac890103178a95`
- `A04.png`: `9cd161dc829c676720fc39a688575a551110db5642c3f8f2ffea7f354b3a66e1`
- `A05.png`: `2cbb02a538f5d6c4941360e310d9d6d80e128b8745bce2828ca7a6de9601a491`
- `A06.png`: `6534d2123493e235ee2269f26d4fe83b85f8a177f52fa6e1e90546849652e64b`
- `A07.png`: `2a83c1cf56e8c702c57c4c686f0312740c45324c2c995607c8c8e23da1afea80`
- `cover-v01.png`: `6ddc1c75a1a4c8b6ba659db085638d6df6c4d7ac0bca6b8c20ec35ac66513f4a`
