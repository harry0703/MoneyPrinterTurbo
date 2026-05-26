# 中文字体安装指南 - Chinese Artistic Fonts

本指南帮助您添加免费可商用的中文艺术字体、书法字体和手写字体。

## 推荐免费中文字体 (全部可免费商用)

### 一、书法/毛笔字体 (Calligraphy/Brush Fonts)

| 字体名称 | 风格 | 适用场景 | 下载链接 | 推荐指数 |
|----------|------|----------|----------|----------|
| **站酷庆科黄油体** | 圆润书法 | 现代、年轻化标题 | https://www.zcool.com.cn/special/zcoolfonts/ | ⭐⭐⭐⭐⭐ |
| **汉仪字库-玄鹤** | 行书书法 | 优雅、文化感标题 | https://www.hanyi.com.cn/ | ⭐⭐⭐⭐⭐ |
| **王强书法体** | 手写书法 | 个性化标题 | 站酷搜索"王强书法体" | ⭐⭐⭐⭐ |
| **钟齐流江毛草** | 毛草书法 | 古风、传统标题 | https://www.fonts.net.cn/ | ⭐⭐⭐⭐ |
| **演示秋鸿体** | 行楷书法 | 文艺、诗意标题 | https://foundertype.com/ | ⭐⭐⭐⭐ |

### 二、艺术/创意字体 (Artistic/Creative Fonts)

| 字体名称 | 风格 | 适用场景 | 下载链接 | 推荐指数 |
|----------|------|----------|----------|----------|
| **站酷酷黑体** | 现代黑体 | 力量感标题 | https://www.zcool.com.cn/special/zcoolfonts/ | ⭐⭐⭐⭐⭐ |
| **站酷文艺体** | 文艺手写 | 清新、文艺标题 | https://www.zcool.com.cn/special/zcoolfonts/ | ⭐⭐⭐⭐⭐ |
| **站酷快乐体** | 活泼手写 | 轻松、娱乐标题 | https://www.zcool.com.cn/special/zcoolfonts/ | ⭐⭐⭐⭐ |
| **庞门正道标题体** | 粗体艺术 | 醒目大标题 | http://www.pmzdao.com/ | ⭐⭐⭐⭐⭐ |
| **锐字潮字库** | 潮酷艺术 | 时尚、年轻标题 | https://reeji.com/ | ⭐⭐⭐⭐ |

### 三、经典/传统字体 (Classic/Traditional Fonts)

| 字体名称 | 风格 | 适用场景 | 下载链接 | 推荐指数 |
|----------|------|----------|----------|----------|
| **思源宋体** | 传统宋体 | 正式、文档标题 | https://fonts.google.com/noto/specimen/Noto+Serif+SC | ⭐⭐⭐⭐⭐ |
| **思源黑体** | 现代黑体 | 通用、清晰标题 | https://fonts.google.com/noto/specimen/Noto+Sans+SC | ⭐⭐⭐⭐⭐ |
| **方正书宋** | 经典宋体 | 书籍、文章标题 | https://www.foundertype.com/ | ⭐⭐⭐⭐ |
| **华康楷体** | 传统楷体 | 古典、文化标题 | https://www.dynacw.com/ | ⭐⭐⭐⭐ |

### 四、现代/圆体字体 (Modern/Rounded Fonts)

| 字体名称 | 风格 | 适用场景 | 下载链接 | 推荐指数 |
|----------|------|----------|----------|----------|
| **猫啃网糖圆体** | 圆润可爱 | 温馨、亲和标题 | https://www.maoken.com/ | ⭐⭐⭐⭐⭐ |
| **站酷小薇LOGO体** | 简洁现代 | 品牌、LOGO标题 | https://www.zcool.com.cn/special/zcoolfonts/ | ⭐⭐⭐⭐ |
| **得意黑** | 现代斜体 | 时尚、动感标题 | https://github.com/atelier-anchor/smiley-sans | ⭐⭐⭐⭐⭐ |

## 安装步骤

### 步骤 1: 下载字体

#### 方法一: 从推荐网站下载
1. 访问上方下载链接
2. 找到字体下载按钮
3. 下载 ZIP 压缩包
4. 解压获取 `.ttf` 或 `.ttc` 文件

#### 方法二: 从猫啃网批量下载
1. 访问 https://www.maoken.com/all-fonts
2. 筛选"书法"、"手写"、"创意"类型
3. 关注公众号获取下载链接
4. 批量下载字体包

#### 方法三: 从站酷下载
1. 访问 https://www.zcool.com.cn/special/zcoolfonts/
2. 选择免费字体下载
3. 所有站酷免费字体均可商用

### 步骤 2: 安装字体文件

1. 解压下载的 ZIP 文件
2. 找到 `.ttf` 或 `.ttc` 文件
3. 复制到: `d:\src\MoneyPrinterTurboCN\resource\fonts\`
4. 确保文件名清晰易识别

**推荐命名方式:**
```
ZhanKu-QingKeHuangYou.ttf     # 站酷庆科黄油体
ZhanKu-KuHei.ttf              # 站酷酷黑体
ZhanKu-WenYi.ttf              # 站酷文艺体
PangMenZhengDao-Biaoti.ttf    # 庞门正道标题体
SiYuan-SongTi.ttf             # 思源宋体
SiYuan-HeiTi.ttf              # 思源黑体
DeYi-Hei.ttf                  # 得意黑
MaoKen-TangYuan.ttf           # 猫啃网糖圆体
```

### 步骤 3: 更新代码

#### 更新前端字体列表

编辑 `vue-frontend/src/views/TitleSettings.vue` (约第328行):

```javascript
const availableFonts = [
  // 原有字体
  'MicrosoftYaHeiBold.ttc',
  'MicrosoftYaHeiNormal.ttc',
  'STHeitiLight.ttc',
  'STHeitiMedium.ttc',
  'Charm-Bold.ttf',
  'Charm-Regular.ttf',
  'UTM Kabel KT.ttf',
  // 英文装饰字体
  'Lobster-Regular.ttf',
  'Pacifico-Regular.ttf',
  'BebasNeue-Regular.ttf',
  // 中文艺术字体 ⭐ 新增
  'ZhanKu-QingKeHuangYou.ttf',  // 站酷庆科黄油体
  'ZhanKu-KuHei.ttf',           // 站酷酷黑体
  'ZhanKu-WenYi.ttf',           // 站酷文艺体
  'ZhanKu-KuaiLe.ttf',          # 站酷快乐体
  'PangMenZhengDao-Biaoti.ttf', // 庞门正道标题体
  'SiYuan-SongTi.ttf',          // 思源宋体
  'SiYuan-HeiTi.ttf',           // 思源黑体
  'DeYi-Hei.ttf',               // 得意黑
  'MaoKen-TangYuan.ttf',        // 猫啃网糖圆体
  'WangQiang-ShuFa.ttf',        // 王强书法体
];
```

#### 添加中文风格预设

编辑 `app/services/title_styles.py`, 添加:

```python
# 中文艺术风格预设
"zhanhuang_you": {
    "name": "站酷黄油",
    "description": "圆润现代，年轻活力",
    "params": {
        "title_font_name": "ZhanKu-QingKeHuangYou.ttf",
        "title_font_size": 80,
        "title_text_color": "#FFB800",
        "title_stroke_color": "#FF6B00",
        "title_stroke_width": 2.0,
        "title_background_color": "transparent",
        "title_position": "center",
        "title_margin": 0.05,
        "title_margin_left": 0.05,
        "title_margin_right": 0.05,
        "title_animation": "fade_in",
        "title_animation_duration": 0.5
    }
},
"zhanKu_wenyi": {
    "name": "站酷文艺",
    "description": "清新文艺，手感觉",
    "params": {
        "title_font_name": "ZhanKu-WenYi.ttf",
        "title_font_size": 76,
        "title_text_color": "#5D4037",
        "title_stroke_color": "#8D6E63",
        "title_stroke_width": 1.5,
        "title_background_color": "transparent",
        "title_position": "center",
        "title_margin": 0.05,
        "title_margin_left": 0.05,
        "title_margin_right": 0.05,
        "title_animation": "slide_up",
        "title_animation_duration": 0.6
    }
},
# ... 更多预设
```

## 快速开始推荐

### 必备5款中文字体 (优先下载)

如果只下载5款字体，推荐这些:

1. **站酷庆科黄油体** - 最百搭的中文艺术字体
2. **庞门正道标题体** - 最适合大标题的粗体
3. **思源宋体** - 最经典的宋体
4. **站酷文艺体** - 最清新的手写体
5. **得意黑** - 最时尚的现代字体

这5款覆盖: 圆润、粗体、传统、文艺、现代 五种风格。

## 字体使用技巧

### 书法字体使用建议
- **毛笔/书法体**: 适合短标题，不适合长文本
- **行书/草书**: 文化感强，适合古风视频
- **手写体**: 亲切自然，适合Vlog

### 艺术字体使用建议
- **粗体艺术字**: 适合冲击力标题
- **圆润字体**: 适合温馨、亲和内容
- **创意字体**: 适合娱乐、时尚内容

### 颜色搭配建议

| 字体风格 | 推荐文字颜色 | 推荐描边颜色 |
|----------|-------------|-------------|
| 书法体 | 金色 #FFD700 | 深棕 #8B4513 |
| 文艺体 | 深褐 #5D4037 | 浅褐 #8D6E63 |
| 粗体字 | 白色 #FFFFFF | 黑色 #000000 |
| 圆润体 | 粉色 #FF6B9D | 深粉 #C44569 |
| 宋体 | 黑色 #000000 | 透明 |

## 版权说明

所有推荐字体均为**免费可商用**:
- ✅ 个人项目免费使用
- ✅ 商业项目免费使用
- ✅ 视频制作免费使用
- ✅ 社交媒体免费使用
- ❌ 不能直接售卖字体文件

**授权类型说明:**
- **作者声明**: 作者明确声明免费可商用
- **OFL**: 开源字体许可证
- **CC0 1.0**: 完全公共领域

## 字体资源网站

### 中文字体网站
1. **猫啃网** - https://www.maoken.com/ (最全免费字体)
2. **站酷字库** - https://www.zcool.com.cn/special/zcoolfonts/ (优质设计字体)
3. **字体天下** - https://www.fonts.net.cn/ (在线预览下载)
4. **站长字体** - https://font.chinaz.com/ (字体大全)
5. **方正字库** - https://www.foundertype.com/ (专业字库)
6. **100字体** - https://www.100font.com/ (免费商用字体)

### 英文字体网站
1. **Google Fonts** - https://fonts.google.com/ (开源字体)
2. **1001 Fonts** - https://www.1001fonts.com/ (免费字体)
3. **Font Squirrel** - https://www.fontsquirrel.com/ (商用免费)

## 常见问题

### Q: 字体下载后是 .zip 文件怎么办?
A: 需要解压缩，找到里面的 `.ttf` 或 `.ttc` 文件

### Q: 字体文件太大怎么办?
A: 中文字体通常 5-20MB 是正常的，可以正常使用

### Q: 字体在预览中显示但在视频中没有?
A: 
1. 检查文件名是否完全匹配(区分大小写)
2. 检查字体文件是否损坏
3. 查看日志文件是否有字体加载错误
4. 重启应用程序

### Q: 如何确认字体可以商用?
A: 
1. 查看字体下载页面的授权说明
2. 优先选择"作者声明"、"OFL"、"CC0"授权的字体
3. 有疑问时联系字体作者确认

### Q: 繁体字和简体字有什么区别?
A: 
- 简体字体: 适用于中国大陆
- 繁体字体: 适用于港台地区
- 很多字体同时支持简繁体
- 推荐使用支持简繁体的字体

## 字体效果预览

### 站酷庆科黄油体
```
圆润可爱 → 适合年轻化内容
现代化   → 百搭不挑内容
```

### 庞门正道标题体  
```
粗壮有力 → 适合大标题
冲击力强 → 吸引眼球
```

### 站酷文艺体
```
手写感觉 → 亲切自然
清新文艺 → 适合Vlog
```

## 下一步

安装字体后:
1. 创建自定义风格预设
2. 测试不同字体组合
3. 尝试不同颜色和描边效果
4. 分享你最喜欢的字体组合!

---

**最后更新**: 2026-05-26
**字体数量**: 推荐 15+ 款免费可商用中文字体
**状态**: ✅ 准备安装
