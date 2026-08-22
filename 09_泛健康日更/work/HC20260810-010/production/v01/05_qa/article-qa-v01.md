# HC20260810-010 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「七天记录午后变化」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `31240301df4a978a8aa106e10b82f93edde38e4a362ddb0b35f8fcb9828ff379`
- `A02.png`: `3f14660896d699176dec5644206485f8ff609ab0577723c12badc0c2f2a1c4ff`
- `A03.png`: `e196ce5137412540abdb0052c829b2b0b01c9430ae6ddd4b601cf1ebd0c61d80`
- `A04.png`: `60480dee0b007155fb1d6732b4ae11cf7b0e7c20cd30f531b4ee070a2f58a8f0`
- `A05.png`: `f85210d31f0649f75d884b5ee897db8de37af914331ce7a838446d3111fbe551`
- `A06.png`: `e88a90328c606dd4fe1151662e1f839d2d8d50ab56f11f919f893808f30e827b`
- `A07.png`: `241d2e0625fb6a876ce7a31863beeb672cd6461c72329cd316c29427d4b7b58f`
- `cover-v01.png`: `43958456295fcaa1fb1a737106eae1715ba95965843695d9c74c241326113295`
