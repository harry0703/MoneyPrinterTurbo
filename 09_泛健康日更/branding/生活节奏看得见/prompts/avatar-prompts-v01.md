# 头像生成提示词 v01

生成方式：Codex 内置 `image_gen`，三次独立生成；无输入参考图。生成日期：2026-08-10。所有候选原图均保留，不用确定性 SVG 或 Python 代替生成。

## Candidate 01｜日出越过餐盘

```text
Use case: logo-brand
Asset type: square social-media avatar candidate 01
Primary request: create an original, premium flat lifestyle emblem that combines exactly three abstract everyday elements: a rising sun, a simple round plate, and one gently curving walking path.
Scene/backdrop: perfectly flat warm cream #FFF8EC square background.
Subject: the plate is a large calm off-center circle; the sun rises as a clean semicircle behind its upper edge; one deep-teal path sweeps from the lower edge toward the sunrise, reading clearly as a path rather than a check mark.
Style/medium: refined flat vector-like illustration, editorial lifestyle identity, strong memorable silhouette, minimal geometry, matte solid fills, precise smooth edges.
Composition/framing: centered compact emblem with at least 16% empty margin on every side; readable when reduced to 48 px; no element touches the canvas edge.
Color palette: deep teal #087F78, fresh teal #10BFAE, warm cream #FFF8EC, pale peach #F5C79E, charcoal #24313D only.
Constraints: exactly one emblem; no text, no letters, no Chinese, no numbers, no logo wording, no person, no face, no hands, no footprints, no shoes, no food, no utensils, no plant, no heart, no organ, no anatomy, no health cross, no medical symbol, no device, no badge, no seal, no watermark; no gradients; no shadows; no highlights; no 3D; no mockup; no border.
Avoid: clinical blue, red alert color, glossy medical-tech styling, pseudo-professional seal, check-mark silhouette.
```

取舍：保留为候选。日出与路径清楚，留白充足；但餐盘环线较细，48px 时三元素中的“餐盘”弱于 Candidate 02，不选为最终头像。

## Candidate 02｜餐盘中的步行路径（最终入选）

```text
Use case: logo-brand
Asset type: square social-media avatar candidate 02
Primary request: create an original premium flat lifestyle emblem combining exactly three abstract everyday elements: sunlight, one simple round plate, and a walking path.
Scene/backdrop: one uniform solid warm cream #FFF8EC square.
Subject: a bold deep-teal plate seen from above as a solid disk in the lower center; three short pale-peach sun rays fan upward from behind the disk; a single warm-cream S-shaped path is cut through the teal disk as negative space, moving upward toward the sun rays. The three ideas must read as one compact symbol, not separate clip-art icons.
Style/medium: high-end editorial flat vector mark, minimal geometric paper-cut character, absolutely solid color fills, crisp smooth contours, iconic silhouette.
Composition/framing: centered emblem occupying no more than 68% of canvas width and height, at least 16% empty margin on all four sides, robust at 48 px.
Color palette: deep teal #087F78, fresh teal #10BFAE, warm cream #FFF8EC, pale peach #F5C79E, charcoal #24313D only.
Constraints: no text, no letters, no Chinese, no numbers, no wordmark, no person, no face, no body, no hands, no footprints, no shoes, no food, no cutlery, no heart, no leaf, no organ, no anatomy, no health cross, no medical icon, no equipment, no phone, no badge, no seal, no watermark; absolutely no gradients, no shadows, no glow, no lighting effects, no texture, no bevel, no 3D, no mockup, no border.
Avoid: clinical blue, alert red, healthcare brand aesthetic, pseudo-professional credential mark, check mark, location pin.
```

取舍：通过并入选。圆盘、三束日光与负形路径形成单一强轮廓；1024、256、96、48px 均可读，四边可见留白约 22%—28%，没有文字、人物、器械、医学符号、徽章或水印。

## Candidate 03｜环抱日光的斜向路径

```text
Use case: logo-brand
Asset type: square social-media avatar candidate 03
Primary request: create an original premium flat lifestyle emblem unifying exactly three abstract everyday elements: sunlight, a simple plate, and a walking path.
Scene/backdrop: uniform solid deep teal #087F78 square background.
Subject: a warm-cream circular plate appears as a bold crescent open toward the upper right; a small pale-peach rising sun sits within the opening; one fresh-teal walking path arcs diagonally around the plate from lower left to upper right like a calm route ribbon, clearly a path and never a check mark. Fuse the shapes into a compact contemporary symbol.
Style/medium: sophisticated flat editorial vector-like mark, modern Chinese lifestyle magazine identity, minimal shapes, solid matte color fields, strong silhouette, precise smooth curves.
Composition/framing: centered emblem, asymmetrical but balanced, no more than 66% of canvas, at least 17% uninterrupted empty margin on every edge, unmistakable at 48 px.
Color palette: deep teal #087F78 background, fresh teal #10BFAE, warm cream #FFF8EC, pale peach #F5C79E, charcoal #24313D only.
Constraints: no text, no letters, no Chinese, no numbers, no wordmark, no person, no face, no body parts, no footprints, no shoes, no food, no cutlery, no plant, no leaf, no heart, no anatomy, no organ, no health cross, no medical symbol, no device, no badge, no seal, no watermark; absolutely no gradients, no shadows, no glow, no lighting effects, no texture, no 3D, no mockup, no outline frame.
Avoid: clinical blue, alert red, medical-tech aesthetic, certification emblem, map pin, check mark.
```

取舍：保留为候选。斜向动势与深色底有记忆点，留白最大；但小尺寸更容易被读成“自然景观/道路”，餐盘语义不如 Candidate 02 直接，不选为最终头像。

## 最终资产规则

- `avatar-final.png` 由通过 QA 的 Candidate 02 生成标准 1024×1024 版本；不覆盖任何候选。
- 平台上传不得附加账号名、缩写、数字或边框。
- 若平台强制圆形裁切，符号仍须完整落在中心 76% 直径内。
- 任一后续版本都必须重新检查 1024、256、96、48px 与四边至少 12% 留白。
