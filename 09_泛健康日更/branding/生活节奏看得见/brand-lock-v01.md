---
name: "生活节奏看得见｜暖光生活节奏"
version: "1.0"
tags:
  - lifestyle editorial
  - general wellness
  - warm minimalism
  - Chinese social video
author: "MoneyPrinterTurbo content system"
source_url: ""
created: "2026-08-10"

style_prompt_short: >
  为 35—60 岁中国用户设计的暖光生活方式视觉：暖米白留白、深青绿结构、浅桃色日光，
  用圆润但克制的编辑式构图表达睡眠、进餐与日常活动，不借用任何医疗身份或器械暗示。

style_prompt_full: >
  Create a premium, calm Chinese lifestyle editorial system for the account 生活节奏看得见.
  Use only deep teal #087F78, fresh teal #10BFAE, warm cream #FFF8EC, pale peach
  #F5C79E, and charcoal #24313D as brand tokens. Use Noto Sans SC Bold for display
  Chinese and Microsoft YaHei for body Chinese. Build every 1080x1920 cover on an 8px
  grid with 24px corner radii, generous warm-cream negative space, asymmetrical editorial
  balance, one illustration focal area, an 8—12 Chinese-character headline, and a small
  plain series marker. Keep all critical cover content inside x=72—900 and y=160—1500;
  keep the main face/object focal area inside x=96—852 and y=240—1320 so right-side and
  bottom platform controls cannot cover it. Use solid matte fields, natural rounded paths,
  overhead plate-rim/sunlight/single-walking-path motifs, and restrained 160—240ms
  ease-out motion. Avatar production SVGs use only exact token fills with no gradients,
  filters, opacity, shadows, or 3D road perspective; generated avatar images are concept
  sources only and must never be shipped without deterministic flat-vector cleanup. Never use
  clinical blue, alert red, anatomy, organs, clinicians, white coats, stethoscopes, medical
  crosses, devices, data curves, pseudo-professional seals, certification badges, glossy
  medical-tech gradients, paper, pens, notebooks, generated text, logos, or watermarks.

colors:
  primary:
    - name: "深青绿 / Deep Teal"
      hex: "#087F78"
      role: "主结构、深色底、路径与高对比强调；可承载暖米白大字"
    - name: "暖米白 / Warm Cream"
      hex: "#FFF8EC"
      role: "默认背景、留白与深色底上的文字"
  accent:
    - name: "清新青绿 / Fresh Teal"
      hex: "#10BFAE"
      role: "单一动作提示、路径高光和少量节奏点"
    - name: "浅桃色 / Pale Peach"
      hex: "#F5C79E"
      role: "日光、生活温度和插画衬底；不承载深青绿小字"
  neutral:
    - name: "炭灰 / Charcoal"
      hex: "#24313D"
      role: "暖米白或浅桃色上的标题、正文与信息层级"

typography:
  display:
    family: "Noto Sans SC Bold"
    weight: "700"
    style: "中文句式标题，紧凑但不压迫，字距 0 至 -1%，行高 1.12"
  body:
    family: "Microsoft YaHei"
    weight: "400"
    style: "中文正文，左对齐，行高 1.45—1.6"
  caption:
    family: "Microsoft YaHei"
    weight: "600"
    style: "系列标识 36px、辅助文案 42px、footer 36px；不使用全包围徽章"
  rules:
    - "标题仅使用本机已核实存在的 Noto Sans SC Bold：C:/Windows/Fonts/Noto Sans SC Bold (TrueType).otf"
    - "正文仅使用本机已核实存在的 Microsoft YaHei：C:/Windows/Fonts/msyh.ttc"
    - "封面标题限定 8—12 个中文字符，优先两行，每行 4—7 字"
    - "不得把字做成圆章、资质章、医疗徽章或白底蓝字专业机构样式"
    - "图像模型不得生成任何可见中文、英文、数字或 UI；所有文字在 SVG/渲染层确定性生成"

layout:
  grid: "1080×1920 竖屏；8px 基础网格；组件圆角固定 24px"
  alignment: "非对称编辑式布局；标题左对齐，插画焦点与标题形成 40/60 或 50/50 张力"
  aspect_ratio: "9:16"
  notes:
    - "跨平台关键安全区：x=72—900、y=160—1500；任何标题、系列标识、核心动作和必要对象均不得越界"
    - "主视觉焦点建议区：x=96—852、y=240—1320；右侧 x>900 与底部 y>1500 只放可裁切装饰"
    - "标题与插画之间至少 48px；外边距最少 72px；标题块宽度建议 440—760px"
    - "v01 实测：标题首行 Noto Sans SC Bold 80px / kerning -1 宽 397px，右边 x=493；插画从 x=552 开始，净距 59px"
    - "插画必须拆成 core-safe（x=552—852）与 decorative-crop（x=852—960）；只有 decorative-crop 可越过 x=900"
    - "系列标识 36px、辅助文案 42px、footer 36px；必须同时通过 25%（270px 宽）与 360px 手机预览"
    - "卡片、插画窗与色块圆角统一 24px；禁止混用 16/20/28px"
    - "平台封面不叠加平台 Logo；中心裁切预览不得丢失标题或主视觉识别点"
    - "头像符号四边至少保留 12% 空白；默认目标为 16%—24%"

motion:
  transitions:
    - "160—240ms 低幅 ease-out 淡入"
    - "沿 8px 网格的 16—24px 短位移"
    - "硬切或 4—8 帧克制溶解"
  animation_style: >
    生活节奏应被感知为平稳、可跟随的呼吸感。元素最多一次进入和一次强调；路径可做轻微前行，
    日光可做低幅亮度变化，但不弹跳、不旋转徽章、不扫出医疗科技光带。
  pacing: "克制、清晰、温暖；先读标题，再看动作，最后看系列标识"
  audio_cues:
    - "允许柔和木质敲击或轻空气感提示；禁止心电、报警、扫描和设备蜂鸣"

mood:
  keywords:
    - "温暖"
    - "可信"
    - "日常"
    - "克制"
    - "清晰"
  era: "contemporary 2020s"
  cultural_reference: "当代中文生活方式杂志的编辑留白与社区步道的自然弧线"
  avoid:
    - "临床蓝、警示红或蓝白医疗配色"
    - "人体器官、解剖、白大褂、听诊器、医疗十字、检测设备和医学曲线"
    - "证书、盾牌、圆章、权威背书或伪专业标识"
    - "光泽医疗科技渐变、玻璃拟态、霓虹扫描线和金属 3D"
    - "纸、笔、本子作为记录方式"
    - "模型生成文字、数字、Logo、水印或界面"
    - "病名、诊断、检查、治疗、处方或专业身份暗示"

assets:
  reference_images: []
  gsep_elements: []
  html_snippets: []
  color_palette_image:
    url: ""

x_account:
  account_name: "生活节奏看得见"
  account_bio: "记录睡眠、进餐和日常活动中的小习惯"
  audience: "中国大陆 35—60 岁用户"
  content_profile: "general_wellness_uncredentialed"
  avatar_concept: "阳光、餐盘和步行路径组成的简洁生活图形"

x_cover:
  canvas: "1080x1920"
  radius_px: 24
  grid_px: 8
  headline_characters: "8—12"
  critical_safe_area: "x=72—900, y=160—1500"
  focal_safe_area: "x=96—852, y=240—1320"
  illustration_core_safe: "x=552—852, y=352—1264"
  illustration_decorative_crop: "x=852—960, y=352—1264"
  measured_title_right_edge_px: 493
  title_to_illustration_gap_px: 59
  template: "cover/cover-template-v01.svg"
  rendered_preview: "cover/cover-template-v01.png"
  completed_example: "cover/cover-example-v01.svg"
  completed_example_preview: "cover/cover-example-v01.png"
  completed_example_source: "cover/source/cover-lifestyle-source-01.png"

x_avatar:
  final_asset: "avatar/avatar-final.png"
  final_vector: "avatar/avatar-final.svg"
  source_candidate: "avatar/avatar-candidate-01.svg"
  generated_concept_source: "avatar/source/avatar-source-concept-01.png"
  production_method: "built-in image_gen concept followed by deterministic five-token SVG cleanup"
  minimum_empty_margin: "12% each edge"
  verified_sizes: [1024, 256, 96, 48]
  circular_crop_verified: true
  sunlight_geometry: "太阳盘/半圆与三条短直或梯形光线保持可见间隔；禁止圆头光线与日盘粘连成皇冠"

x_platforms:
  orientation: "portrait"
  shared_identity: true
  rules:
    - "视频号、抖音、小红书、快手尽量使用同一名称、简介与头像"
    - "四平台共享安全母版；只替换平台标题/发布说明，不移动安全区内主视觉"
    - "最终提交与账号资料更新均由用户人工完成"
---

## Design Principles

### 1. 日常生活先于“健康行业”

视觉身份必须先被读作普通人的生活节奏，而不是医疗、检测或管理服务。阳光代表一天的开始，餐盘代表进餐，路径代表轻松活动；三者均为生活语义，不承担疗效、资格或专业判断。

### 2. 留白是可信度的一部分

每个画面只设一个主焦点与一个辅助强调。暖米白大面积留白降低“硬销”与“伪权威”感，也给四个平台的裁切和控件留出真实余量。

### 3. 生成概念，确定性生产

图像生成负责无字生活插画与头像概念探索；正式头像必须把对应概念清理为可编辑、五色锁定、无渐变/滤镜/阴影的 SVG，再确定性渲染 PNG。账号名、标题、系列标识、图标和清单全部在 SVG 或后期渲染层生成。任何模型自带文字、Logo、数字、UI 或水印都应退回重做。

### 4. 一个动作，一处强调

清新青绿只指示一个可执行动作。浅桃色只提供日光与生活温度。不得用多色预警、数据仪表或“红黄绿风险”结构制造医疗判断感。

## Cover Production Contract

1. 复制 `cover/cover-template-v01.svg`，保留 1080×1920 画布、24px 圆角和 8px 网格。
2. 将无字生成插画分别放入 `illustration-slot/core-safe` 与 `illustration-slot/decorative-crop`；核心人物/对象只允许出现在 x=552—852，只有环境延展可进入 x=852—960。
3. 将标题替换为 8—12 个中文字符，最多两行；不通过缩小字号硬塞长标题。
4. 系列标识保持为普通行内文字与短横线，不加盾牌、圆章、十字或“认证”外形。
5. 以全帧、25%（270×480）和 360×640 手机预览检查；标题、主视觉、系列归属与 footer 均须可读。
6. 完成态验收使用 `cover/cover-example-v01.svg/png`；模板中的“插画替换区”标签不得出现在上线样张。

## Connectors

### SVG / deterministic render

将颜色映射为 SVG/CSS 变量；中文字体显式指定 `Noto Sans SC` 和 `Microsoft YaHei`。导出前确认字体存在，并以 1080×1920 PNG 渲染。安全区辅助组默认隐藏，只在 QA 预览中显示。

### Image generation

把 `style_prompt_full` 与单镜头内容组合使用。生成图必须无字、无数字、无 Logo、无水印、无 UI，且不得出现禁用医疗或记录物件。插画只占预留 slot，不替代确定性标题层。

### Video / motion graphics

沿 8px 网格排版，最多使用 160—240ms ease-out 入场和 16—24px 位移。禁止弹跳、扫描、心电线、医疗仪表或科技光效。

## Source and Validation Notes

- 本品牌锁依据 `docs/superpowers/specs/2026-08-10-50-episode-general-wellness-design.md` 与 Task 3 简报创建。
- 字体在 2026-08-10 于当前 Windows 主机核实；跨机使用前必须重新核实或打包字体授权。
- 色彩对比以 WCAG 相对亮度公式验证；详见 `qa/brand-qa-v01.md`。
- Fix Cycle 1 依据独立审查重做头像与封面；旧渐变候选和错误焦点 PASS 不再作为有效证据。
