# HC20260810-003 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「吃撑以后先放稳些」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `b17cd00d3f9300c695dd27a46734320ead5c1dd7f9fd3aa44fd722e69370d12b`
- `A02.png`: `aa4ccb6c5cd30ad17fafe3924a0583f90866acea43084cb0fac384f2d1516ba7`
- `A03.png`: `ba43c2ee57913f5378e9b84bd7c7408bd0030952122c39c3ffa590d34c40a006`
- `A04.png`: `7860a8adbecf090ad316e1afe9ec529637f2ae8df8cd5de281c23cbf5a410d45`
- `A05.png`: `ec6d45862f68aa4693fa2d12ab298f7188c9451324bbe3534aa9bec6bb6da8d0`
- `A06.png`: `b17107ff3e4b11bc64f7aebe7719c54bba2a22791efc767eb0631652a9980c74`
- `A07.png`: `2d49af2da45a87fe9a8568b6ec5c7ed5ca528ae9ffb6fa3be91fbe5a7bf97d33`
- `cover-v01.png`: `a2d5b4e0ad4007621c041cd4afc11f54730f4db6dd9b8a4e02e9b859f4d5e544`
