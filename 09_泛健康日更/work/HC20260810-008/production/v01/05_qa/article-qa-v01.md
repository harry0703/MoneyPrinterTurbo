# HC20260810-008 article QA v01

- 机械状态：PASS（规格、文案绑定、文件与哈希；不把文本扫描表述为视觉语义 PASS）。
- 人工视觉语义：必须查看本集 25% 联系表与关键原图；批次结论记录在 Task 7 批次 QA，不替代 Task 8。
- 规格：7/7 文章卡为 1080×1920 PNG；7/7 存在可编辑 SVG；独立平台封面 1/1 为 1080×1920 PNG。
- 原型：A01 hero cover；A02 scene crop；A03–A05 icon-led observations；A06 action；A07 summary。
- 安全区：标题、正文、动作文案在 x=72–900 / y=160–1500。
- 字体：Noto Sans SC Bold / Microsoft YaHei，本机可用。
- 生成图文字：无；文字、数字、图标均为确定性 SVG 层。
- 文本机械扫描：未命中加号／十字符号与指定禁词；图形是否像医疗物件、仪表或设备只能人工判断。
- 封面标题：「嘴馋先记三类线索」（8 字）；来自 Task 5 已批准 A01／平台封面短句，专用构图，非 A01 裁切。
- 25% 人工证据入口：`article-contactsheet-v01.png`。

## SHA-256

- `A01.png`: `3423d29a2abc5024a0a199cbe8b7837793685c507d18f707681a2e845d782517`
- `A02.png`: `fab32155f5f2e6e86c0d3be4230843181364dc13758bd407b20712f61889654d`
- `A03.png`: `67d28305f7570e7941a077e3dc91c6dd3438b4da574cc4422c55c169ee1938b5`
- `A04.png`: `44a781b634923ebd5fd6df5a7ddf3638956333ae31334af858a69887636ca64f`
- `A05.png`: `b8c0738faacf9a26035746cd6c2d9cae49552605726bc85f9d250e7b09e9df09`
- `A06.png`: `f3c9a4fd799a9f00777269af94801657456824422deead373d93cbff22a164a8`
- `A07.png`: `0b25a02fb850da08ecc1c2dfdad2357173c7d5d988e97e39bd3aa5914eafcc9c`
- `cover-v01.png`: `0b1d15d0ae91d57000ba1ca139375f7f95d81b448c6c77900013d84675e26724`
