<div align="center">

# MoneyPrinterTurbo 💸

### أداة توليد الفيديو القصير بالذكاء الاصطناعي

كل ما عليك فعله هو تقديم **موضوع** أو **كلمة مفتاحية** للفيديو، وسيقوم البرنامج تلقائيًا بإنشاء السكريبت واختيار المواد المرئية المناسبة وتوليد الترجمة والموسيقى الخلفية، ثم دمجها في فيديو عالي الجودة — كل ذلك دفعة واحدة.

[![Python](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

العربية | [简体中文](README.md) | [English](README-en.md)

</div>

## المزايا 🎯

- [x] يوفر **WebUI** و**API** و**CLI** وأداء الـ **AI Agent** — اختر طريقة الاستخدام التي تناسبك
- [x] **إنشاء سكريبت الفيديو تلقائيًا بالذكاء الاصطناعي**، أو استخدام سكريبت مخصص
- [x] يدعم أحجام فيديو متعددة عالية الجودة: عمودي `9:16` (1080×1920) وأفقي `16:9` (1920×1080)
- [x] **توليد دفعات** — أنشئ عدة فيديوهات دفعة واحدة واختر أفضلها
- [x] التحكم في مدة عرض كل مقطع لتغيير سرعة تبديل المشاهد
- [x] **دعم اللغة العربية بالكامل** — واجهة عربية، سكريبت عربي، وأصوات عربية جاهزة
- [x] توليد سكريبت الفيديو بعدة لغات
- [x] تركيب صوتي عبر **Edge TTS** و**Azure Speech** و**SiliconFlow** و**Google Gemini** و**Xiaomi MiMo** و**ElevenLabs** و**Chatterbox**، مع معاينة مباشرة
- [x] **ترجمة (Subtitles)** تلقائية مع تخصيص الخط والموضع واللون والحجم والمحيط والخلفية
- [x] **موسيقى خلفية** عشوائية أو مخصصة مع ضبط مستوى الصوت
- [x] استخدام **مواد محلية** أو التحميل من **Pexels** و**Pixabay** و**Coverr**
- [x] يدعم مزودي نماذج رئيسيين: **Kimi / Moonshot AI** و**OpenAI** و**Google Gemini** و**DeepSeek** و**Qwen** و**Azure OpenAI** و**Volcengine Ark** و**xAI Grok** و**MiniMax** و**Xiaomi MiMo** وغيرهم
- [x] النشر التلقائي للمنصات: **TikTok** و**Instagram** و**YouTube Shorts**

## دعم اللغة العربية 🌍

- **الواجهة**: قائمة لغة كاملة بالعربية (اختر "العربية" من أعلى الصفحة)
- **السكريبت**: اختر `ar-SA` أو `ar-EG` كلغة للسكريبت ليُكتب بالعربية
- **الأصوات العربية**:
  - **Edge TTS** (افتراضي، بدون مفتاح API): 32 صوتًا عربيًا جاهزًا (مثل `ar-EG-SalmaNeural` و`ar-SA-HamedNeural`)
  - **Google Gemini TTS**: 30 صوتًا عربيًا (اختر الصوت الذي تظهر بجانبه كلمة "العربية")
  - **ElevenLabs**: يدعم العربية تلقائيًا عبر نموذج `eleven_multilingual_v2`

## المتطلبات 📦

- النظام: Windows 10 أو macOS 11 أو توزيعات Linux الحديثة
- Python 3.11 أو أحدث (يُفضل 3.11)
- GPU غير مطلوب (مفيد للتسريع عند استخدام Whisper المحلي أو التوليد الدفعي)

## البدء السريع 🚀

### Windows — حزمة التشغيل بنقرة واحدة

حمّل أحدث إصدار من [GitHub Releases](https://github.com/harry0703/MoneyPrinterTurbo/releases/latest) وفك الضغط (يُفضل مسارًا بدون أحرف عربية أو فراغات)، ثم شغّل `start.bat`. يُحدَّث الكود تلقائيًا عند الحاجة وتفتح الواجهة في المتصفح.

> ملاحظة: إذا فتحت الصفحة فارغة، استخدم Chrome أو Edge.

### التثبيت اليدوي

```shell
git clone https://github.com/harry0703/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo

# مع uv (مُوصى به)
uv python install 3.11
uv sync --frozen

# أو مع venv + pip
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# تشغيل الواجهة
.\webui.bat            # Windows
sh webui.sh            # macOS / Linux
```

ثم افتح المتصفح على `http://127.0.0.1:8501`.

### استخدام سطر الأوامر (CLI)

```shell
python cli.py --video-subject "ما هي تقنية الذكاء الاصطناعي" --video-language ar-SA
```

## النشر داخل الحاويات (Docker) 🐳

```shell
cd MoneyPrinterTurbo
docker compose -f docker-compose.release.yml up
```

ثم افتح `http://127.0.0.1:8501` للواجهة أو `http://127.0.0.1:8080/docs` لوثائق الـ API.

## التكوين ⚙️

في أول تشغيل يُنشأ ملف `config.toml` تلقائيًا من `config.example.toml`. يمكن ضبط مزود النموذج وواجهات المواد ومفاتيح API مباشرة من الواجهة (الإعدادات).

## توليد الصوت 🗣

- الافتراضي: **Edge TTS** مجاني بدون مفتاح API (يظهر في الواجهة باسم *Azure TTS V1*)
- تتوفر أيضًا Azure TTS V2 وSiliconFlow وGoogle Gemini وXiaomi MiMo وElevenLabs وChatterbox
- قائمة أصوات Edge TTS: [voice-list.txt](./docs/voice-list.txt)

## الترجمة 📜

- **edge** (الافتراضي): تُنشأ من الطوابع الزمنية لتركيب الصوت — سريعة وبدون GPU
- **whisper**: عبر `faster-whisper` المحلي لدقة أعلى في توقيت الترجمة

```toml
[app]
subtitle_provider = "whisper"

[whisper]
model_size = "large-v3-turbo"
```

## الأسئلة الشائعة 🤔

<details>
<summary>كيف أنشر على TikTok وInstagram وYouTube Shorts؟</summary>

سجّل في [Upload-Post](https://upload-post.com/) واحصل على مفتاح API، ثم أضف في `config.toml`:

```toml
[app]
upload_post_enabled = true
upload_post_api_key = "your-api-key"
upload_post_username = "your-username"
upload_post_platforms = ["tiktok", "instagram", "youtube"]
```

</details>

<details>
<summary>خطأ: RuntimeError: No ffmpeg exe could be found</summary>

حمّل ffmpeg من https://www.gyan.dev/ffmpeg/builds/ وفك الضغط ثم اضبط المسار:

```toml
[app]
ffmpeg_path = "C:\\path\\to\\ffmpeg.exe"
```

</details>

## المساهمة 🤝

نرحب بالمساهمات. أنشئ فرعًا (branch) من الكود وقدم Pull Request. للمناقشات: [الأساسيات](https://github.com/harry0703/MoneyPrinterTurbo/issues) أو [Discord](https://harryai.cc).

## الترخيص 📝

انظر [LICENSE](LICENSE)