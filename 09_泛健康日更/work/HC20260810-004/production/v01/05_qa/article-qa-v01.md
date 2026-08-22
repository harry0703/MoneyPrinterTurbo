# HC20260810-004 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「七天对比坐走感受」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `56616a5570deb1966f73370e6ef43023046520ea0e02e96e583f110796aaf4a5`
- `A02.png`: `5d3ff01fd83f0f498a15eefa14e1fcd810d7ddeb64202724f9df83d453d67177`
- `A03.png`: `16a214c779582a7c73353ae697df18434d15e6d3efdef9b08d79669aa7d42cff`
- `A04.png`: `540a64bd96738516e868ba3cd29f9afa7c4f6baace34392b28b89dc05e14771a`
- `A05.png`: `1d7c04fec5b674438bd8a5b4e30a35ee8aead90f9ab2c69298714c838a257305`
- `A06.png`: `88dcaa44d10e2d3c55841a26504ee65821ec62ca70b50fbd0a747e30ba1d38b9`
- `A07.png`: `23cb58451d444ad63d35221420750eec0efacfb7588206e8bf0decbdde92ab59`
- `cover-v01.png`: `2e2d5315fc0196d804df496259e2b59b7648b7fefb1255dfead2abcac61d6bea`
