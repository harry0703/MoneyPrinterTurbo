# HC20260810-005 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「下午卡住简短重启」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `24b9a734e9be8703c672fa37761b98861bac7f1c2af15c3f5a3175caf609d0ba`
- `A02.png`: `4fcc8ec18de67d0a4392bea4bf431e939a1ee9cd6f9ff7569c07eb2b68213dcf`
- `A03.png`: `df60c7b528f1e838e4118cd3f829915f6e6ebbc2b5e95a965b0369ee362355d5`
- `A04.png`: `6096b9c9726ae6b3f3b47221af7fd82ca90c346bb488294675e164e0747f7431`
- `A05.png`: `8a7432149687666b09a71693f2f3617522a8708f57ce59e892c2bc2dad611733`
- `A06.png`: `66fbe55038bda3f6519fbae08c2deba28bcce8a9b7b6614df5dc3549250c0019`
- `A07.png`: `1459cc230cb2d9b373b0b53a6fa9f2f89183362af0bc48b44f5938327bc85096`
- `cover-v01.png`: `6383e1c9efb6a5a12220d8b520c62ad8dcbda2390c7692cfaf09fc51a6638a61`
