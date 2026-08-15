# HC20260810-006 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「午休看清三个时点」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `1929bf7fa57a61213a3efabed19e3f74ce6538ee89d22f55a6b7f516507aab3d`
- `A02.png`: `cd83a2e8c56ddb62ae8ddea1f12af676af31ced7adff28b7805cac0f02ce0509`
- `A03.png`: `b6bcd185f065d54b331d4eb803cd25bec9446ff5f2c68a9716bcb30c18fb46d4`
- `A04.png`: `9bcd95a78457f8d51c7d43753a0634362ba61f2dcf59ae68aa34c88a55359f33`
- `A05.png`: `6feae30f7337f04e18eb5920bc794093cc8199c3cd9c8744a5e0e229f0d36447`
- `A06.png`: `673520d7d6a1501760cb50d0029bcd95fa608b8b6c6834377f50edb8597dac4b`
- `A07.png`: `41daedb247f329a958269523d0abbae23438af922f923038408785a9c6b2aef1`
- `cover-v01.png`: `f94b0ef44981c749d423c15b72361603ce3d2d4d593043c881103bc1aaa8c2ce`
