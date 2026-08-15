# HC20260810-001 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「午后犯困先看三项」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `325f1a73d1182fd01638801283acf9757cd8a401adc3072099a158316d58658d`
- `A02.png`: `6d5b43265741c46acc85d1ee06890395c454e4e4b348ac7ca374056a79cfc020`
- `A03.png`: `3a84d71dfbd7e4e0985cae5781ed054c79de31490ca9caa22444d56baba35f0d`
- `A04.png`: `03aab9ecb9bbd9fda81306cb326727e50935bce669a5cbdc443a23005a27051e`
- `A05.png`: `ff7e6119ef323a69248de609c14759937181832c882115e75c8370c75bed3c3e`
- `A06.png`: `4242fc7a9158b2c4cc1ba4ced07c2af5d1f3f7c4cddbc2d0d07eed8608315b81`
- `A07.png`: `1d71017d673668da7b01347ad045fc0f253d211475421865283cc11048ead20a`
- `cover-v01.png`: `1043c5c4afc7c2fa14ca5fa1ed7064853eada84d37503a903b1f7ac78c5219e7`
