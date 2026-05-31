import streamlit as st
import os
import tempfile
import json
import subprocess
import requests
import re

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "openai_api_key": "",
            "openrouter_api_key": "",
            "pexels_api_key": "",
            "pixabay_api_key": "",
            "llm_provider": "OpenAI",
            "model_name": "",
            "base_url": ""
        }

def save_config(data: dict):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False

def run_preview(voice_name: str, text: str) -> bytes:
    with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    try:
        subprocess.run([
            "edge-tts",
            "--voice", voice_name,
            "--text", text,
            "--write-media", tmp_path
        ], check=True, capture_output=True)
        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

def generate_script(topic, duration, language, cfg):
    duration_words = {
        "30 seconds": "80-100",
        "1 minute": "150-180",
        "3 minutes": "450-500",
        "5 minutes": "750-800",
    }
    word_count = duration_words.get(duration, "150-180")
    lang_map = {
        "English": "English",
        "Urdu": "Urdu",
        "Hindi": "Hindi",
        "Arabic": "Arabic",
        "Chinese": "Chinese",
    }
    lang = lang_map.get(language, "English")
    prompt = f"""Write an engaging faceless YouTube video script about: {topic}
Language: {lang}
Word count: {word_count} words
Style: Engaging, informative, conversational
NO stage directions, NO [Music], NO [Scene], just pure narration.
Start with a hook. End with a call to action."""

    openrouter_key = cfg.get("openrouter_api_key") or \
        os.environ.get("OPENROUTER_API_KEY", "")
    model = cfg.get("model_name") or \
        "mistralai/mistral-7b-instruct:free"
    base_url = cfg.get("base_url") or \
        "https://openrouter.ai/api/v1"

    headers = {
        "Authorization": f"Bearer {openrouter_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://huggingface.co",
        "X-Title": "BrainReel"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
    }
    resp = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]

def generate_voice(script, voice):
    with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False, dir="/tmp") as f:
        voice_path = f.name
    subprocess.run([
        "edge-tts",
        "--voice", voice,
        "--text", script,
        "--write-media", voice_path
    ], check=True, capture_output=True)
    return voice_path

def fetch_pexels_videos(keyword, count, cfg):
    pexels_key = cfg.get("pexels_api_key") or \
        os.environ.get("PEXELS_API_KEY", "")
    headers = {"Authorization": pexels_key}
    params = {
        "query": keyword,
        "per_page": count,
        "orientation": "portrait",
        "size": "medium"
    }
    resp = requests.get(
        "https://api.pexels.com/videos/search",
        headers=headers,
        params=params,
        timeout=15
    )
    resp.raise_for_status()
    videos = resp.json().get("videos", [])
    urls = []
    for v in videos:
        for f in v.get("video_files", []):
            if f.get("quality") in ["hd", "sd"] and \
               f.get("file_type") == "video/mp4":
                urls.append(f["link"])
                break
    return urls

def download_video(url, idx):
    path = f"/tmp/clip_{idx}.mp4"
    resp = requests.get(url, timeout=60, stream=True)
    with open(path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    return path

def compose_video(clip_paths, voice_path, aspect,
                  font_size, subtitle_color, position, script):
    output_path = "/tmp/brainreel_output.mp4"
    if "9:16" in aspect:
        width, height = 1080, 1920
    else:
        width, height = 1920, 1080

    result = subprocess.run([
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "csv=p=0", voice_path
    ], capture_output=True, text=True)
    try:
        total_duration = float(result.stdout.strip())
    except Exception:
        total_duration = 60.0

    clip_duration = total_duration / max(len(clip_paths), 1)
    scaled_clips = []
    for i, clip in enumerate(clip_paths):
        out = f"/tmp/scaled_{i}.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-i", clip,
            "-t", str(clip_duration),
            "-vf",
            f"scale={width}:{height}:"
            f"force_original_aspect_ratio=increase,"
            f"crop={width}:{height}",
            "-c:v", "libx264", "-an", out
        ], capture_output=True)
        scaled_clips.append(out)

    concat_list = "/tmp/concat.txt"
    with open(concat_list, "w") as f:
        for clip in scaled_clips:
            f.write(f"file '{clip}'\n")

    concat_out = "/tmp/concat_out.mp4"
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", concat_list,
        "-c", "copy", concat_out
    ], capture_output=True)

    pos_map = {
        "Bottom": f"(w-text_w)/2:h-{font_size * 3}",
        "Center": "(w-text_w)/2:(h-text_h)/2",
        "Top": f"(w-text_w)/2:{font_size}",
    }
    pos = pos_map.get(position, f"(w-text_w)/2:h-{font_size * 3}")
    color = subtitle_color.lstrip("#")
    ffmpeg_color = f"#{color}"
    clean_script = re.sub(r"[^\w\s.,!?]", "", script)
    clean_script = clean_script[:150] + "..."

    subprocess.run([
        "ffmpeg", "-y",
        "-i", concat_out,
        "-i", voice_path,
        "-c:v", "libx264",
        "-c:a", "aac",
        "-shortest",
        "-vf",
        f"drawtext=text='{clean_script}':"
        f"fontsize={font_size}:"
        f"fontcolor={ffmpeg_color}:"
        f"x={pos.split(':')[0]}:"
        f"y={pos.split(':')[1]}:"
        f"box=1:boxcolor=black@0.5:boxborderw=5",
        output_path
    ], capture_output=True)
    return output_path

video_subject = ""

st.set_page_config(
    page_title="BrainReel — AI Video Generator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #0e0e0e;
    color: #f0f0f0;
}
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: visible !important;}
[data-testid="stAppDeployButton"] { display: none !important; }
button[data-testid="collapsedControl"] {
    visibility: visible !important;
    display: flex !important;
    opacity: 1 !important;
    background: linear-gradient(135deg, #7c3aed, #2563eb) !important;
    border-radius: 8px !important;
    border: none !important;
    width: 40px !important;
    height: 40px !important;
    box-shadow: 0 4px 15px rgba(124,58,237,0.5) !important;
}
button[data-testid="collapsedControl"] svg { fill: white !important; }
button[data-testid="expandedControl"] {
    visibility: visible !important;
    display: flex !important;
    opacity: 1 !important;
    background: rgba(255,255,255,0.1) !important;
    border: 1px solid rgba(255,255,255,0.2) !important;
    border-radius: 8px !important;
    width: 36px !important;
    height: 36px !important;
}
button[data-testid="expandedControl"] svg { fill: #f0f0f0 !important; }
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    border-right: 1px solid #2a2a4a;
}
.brand-logo { text-align: center; padding: 20px 0 10px 0; }
.brand-title {
    font-size: 28px; font-weight: 700;
    background: linear-gradient(90deg, #a78bfa, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.brand-sub { font-size: 12px; color: #888; margin-top: 4px; }
.card-title {
    font-size: 14px; font-weight: 600; color: #a78bfa;
    margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px;
}
.stButton > button {
    background: linear-gradient(90deg, #7c3aed, #2563eb);
    color: white; border: none; border-radius: 8px;
    font-weight: 600; padding: 10px 24px;
    width: 100%; transition: opacity 0.2s;
}
.stButton > button:hover { opacity: 0.85; color: white; }
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    background: #0e0e1a !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 8px !important;
    color: #f0f0f0 !important;
}
.stTabs [data-baseweb="tab-list"] {
    background: #1a1a2e; border-radius: 10px; padding: 4px; gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent; border-radius: 8px;
    color: #888; font-weight: 600; padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(90deg, #7c3aed, #2563eb) !important;
    color: white !important;
}
.badge {
    display: inline-block; padding: 3px 10px;
    border-radius: 20px; font-size: 11px; font-weight: 600;
}
.badge-ready { background: #064e3b; color: #34d399; }
.badge-warn  { background: #451a03; color: #fb923c; }
.section-header {
    font-size: 11px; text-transform: uppercase;
    letter-spacing: 2px; color: #555; margin: 20px 0 8px 0;
}
.key-status {
    font-size: 12px; padding: 4px 10px;
    border-radius: 6px; margin-top: 4px;
    display: inline-block;
}
.key-set { background: #064e3b; color: #34d399; }
.key-empty { background: #1a1a2e; color: #555; }
</style>
""", unsafe_allow_html=True)

VOICE_MAP = {
    "en-US-AriaNeural — English Female 🇺🇸": "en-US-AriaNeural",
    "en-US-GuyNeural — English Male 🇺🇸": "en-US-GuyNeural",
    "ur-PK-UzmaNeural — Urdu Female 🇵🇰": "ur-PK-UzmaNeural",
    "ur-PK-AsadNeural — Urdu Male 🇵🇰": "ur-PK-AsadNeural",
    "hi-IN-SwaraNeural — Hindi Female 🇮🇳": "hi-IN-SwaraNeural",
    "hi-IN-MadhurNeural — Hindi Male 🇮🇳": "hi-IN-MadhurNeural",
    "ar-SA-ZariyahNeural — Arabic Female 🇸🇦": "ar-SA-ZariyahNeural",
    "zh-CN-XiaoxiaoNeural — Chinese Female 🇨🇳": "zh-CN-XiaoxiaoNeural",
}

PREVIEW_TEXTS = {
    "en-US-AriaNeural": "Hello! I am Aria. I will be the voice of your video.",
    "en-US-GuyNeural": "Hello! I am Guy. I will be the voice of your video.",
    "ur-PK-UzmaNeural": "السلام علیکم! میں آپ کی ویڈیو کی آواز ہوں۔",
    "ur-PK-AsadNeural": "السلام علیکم! میں آپ کی ویڈیو کی آواز ہوں۔",
    "hi-IN-SwaraNeural": "नमस्ते! मैं आपके वीडियो की आवाज़ हूँ।",
    "hi-IN-MadhurNeural": "नमस्ते! मैं आपके वीडियो की आवाज़ हूँ।",
    "ar-SA-ZariyahNeural": "مرحبا! أنا صوت الفيديو الخاص بك.",
    "zh-CN-XiaoxiaoNeural": "你好！我是你视频的声音。",
}

MODEL_LISTS = {
    "OpenAI": [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo",
        "gpt-3.5-turbo", "Custom (type below)"
    ],
    "OpenRouter": [
        "deepseek/deepseek-chat",
        "deepseek/deepseek-r1",
        "google/gemini-flash-1.5",
        "google/gemini-pro-1.5",
        "meta-llama/llama-3.1-8b-instruct:free",
        "meta-llama/llama-3.3-70b-instruct",
        "mistralai/mixtral-8x7b-instruct",
        "mistralai/mistral-7b-instruct:free",
        "anthropic/claude-3-haiku",
        "anthropic/claude-3.5-sonnet",
        "qwen/qwen-2.5-72b-instruct",
        "microsoft/phi-3-medium-128k-instruct:free",
        "Custom (type below)"
    ],
    "DeepSeek": [
        "deepseek-chat", "deepseek-reasoner",
        "Custom (type below)"
    ],
    "Moonshot": [
        "moonshot-v1-8k", "moonshot-v1-32k",
        "moonshot-v1-128k", "Custom (type below)"
    ],
    "Google Gemini": [
        "gemini-1.5-flash", "gemini-1.5-pro",
        "gemini-2.0-flash", "Custom (type below)"
    ],
    "Ollama": [
        "llama3", "llama3.1", "mistral",
        "qwen2.5", "deepseek-r1",
        "Custom (type below)"
    ],
}

cfg = load_config()

with st.sidebar:
    st.markdown("""
    <div class="brand-logo">
        <div class="brand-title">🎬 BrainReel</div>
        <div class="brand-sub">AI Faceless Video Generator</div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    st.markdown('<div class="section-header">Navigation</div>',
                unsafe_allow_html=True)
    page = st.radio(
        label="",
        options=["🎬 Generate Video", "⚙️ Settings",
                 "📜 History", "📊 Analytics"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.markdown('<div class="section-header">Status</div>',
                unsafe_allow_html=True)
    api_set = bool(
        cfg.get("openai_api_key") or
        cfg.get("openrouter_api_key") or
        os.environ.get("OPENROUTER_API_KEY"))
    if api_set:
        st.markdown(
            '<span class="badge badge-ready">✓ API Ready</span>',
            unsafe_allow_html=True)
    else:
        st.markdown(
            '<span class="badge badge-warn">⚠ API Not Set</span>',
            unsafe_allow_html=True)
    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("v2.0 · BrainReel Edition")

if page == "🎬 Generate Video":
    st.markdown("## 🎬 Generate Video")
    st.caption("Fill in the details below and let AI do the magic!")
    tab1, tab2, tab3 = st.tabs(
        ["📝 Script", "🎨 Style", "🔊 Voice & Music"])

    with tab1:
        st.markdown('<div class="card-title">📝 Video Script</div>',
                    unsafe_allow_html=True)
        video_subject = st.text_input(
            "Video Topic / Subject",
            placeholder="e.g. 5 mind-blowing facts about black holes")
        script_mode = st.radio(
            "Script Mode",
            ["🤖 AI Auto Generate", "✍️ Write Manually"],
            horizontal=True)
        if script_mode == "✍️ Write Manually":
            manual_script = st.text_area(
                "Your Script",
                placeholder="Yahan script likho...",
                height=180)
        else:
            manual_script = ""
        col1, col2 = st.columns(2)
        with col1:
            video_language = st.selectbox(
                "Language",
                ["English", "Urdu", "Hindi", "Arabic", "Chinese"])
        with col2:
            video_length = st.selectbox(
                "Video Length",
                ["30 seconds", "1 minute", "3 minutes", "5 minutes"])

    with tab2:
        st.markdown('<div class="card-title">🎨 Visual Style</div>',
                    unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            video_aspect = st.selectbox(
                "Aspect Ratio",
                ["9:16 (Vertical / TikTok)",
                 "16:9 (Horizontal / YouTube)"])
        with col2:
            st.selectbox("Video Source", ["Pexels (Free)"])
        st.markdown("**Subtitle Settings**")
        col3, col4 = st.columns(2)
        with col3:
            font_size = st.slider("Font Size", 30, 100, 60)
        with col4:
            subtitle_position = st.selectbox(
                "Position", ["Bottom", "Center", "Top"])
        subtitle_color = st.color_picker(
            "Subtitle Color", "#FFFFFF")

    with tab3:
        st.markdown('<div class="card-title">🔊 Voice & Music</div>',
                    unsafe_allow_html=True)
        voice_display = st.selectbox(
            "TTS Voice", list(VOICE_MAP.keys()))
        selected_voice = VOICE_MAP[voice_display]
        col_prev, col_empty = st.columns([1, 2])
        with col_prev:
            preview_btn = st.button("🔊 Preview Voice")
        if preview_btn:
            with st.spinner("🎙️ Voice generate ho rahi hai..."):
                try:
                    preview_text = PREVIEW_TEXTS.get(
                        selected_voice, "Hello! This is a preview.")
                    audio_bytes = run_preview(
                        selected_voice, preview_text)
                    st.audio(audio_bytes, format="audio/mp3")
                    st.success("✅ Preview ready!")
                except Exception as e:
                    st.error(f"❌ Error: {e}")
        st.slider("Background Music Volume", 0, 100, 30)
        st.selectbox("Background Music",
            ["Random", "Calm", "Upbeat", "Cinematic", "No Music"])

    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        generate_btn = st.button(
            "🚀 Generate Video", use_container_width=True)

    # ── Session State Reset Button ──
    if "gen_step" in st.session_state and \
            st.session_state.gen_step > 0:
        if st.button("🔄 Naya Video Banao — Reset"):
            for key in ["gen_step", "gen_script",
                        "gen_voice", "gen_clips", "gen_output"]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()

    if generate_btn:
        if not video_subject and not manual_script:
            st.error("⚠️ Video topic ya script enter karo pehle!")
        else:
            pexels_key = cfg.get("pexels_api_key") or \
                os.environ.get("PEXELS_API_KEY", "")
            openrouter_key = cfg.get("openrouter_api_key") or \
                os.environ.get("OPENROUTER_API_KEY", "")

            if not openrouter_key:
                st.error("❌ OpenRouter API key Settings mein daalo!")
            elif not pexels_key:
                st.error("❌ Pexels API key Settings mein daalo!")
            else:
                # Session state init
                if "gen_step" not in st.session_state:
                    st.session_state.gen_step = 0
                if "gen_script" not in st.session_state:
                    st.session_state.gen_script = ""
                if "gen_voice" not in st.session_state:
                    st.session_state.gen_voice = ""
                if "gen_clips" not in st.session_state:
                    st.session_state.gen_clips = []
                if "gen_output" not in st.session_state:
                    st.session_state.gen_output = ""

                try:
                    progress = st.progress(0)
                    status_box = st.empty()

                    # Step 1
                    if st.session_state.gen_step < 1:
                        status_box.info(
                            "📝 Step 1/4 — Script generate ho rahi hai...")
                        if manual_script:
                            st.session_state.gen_script = manual_script
                        else:
                            st.session_state.gen_script = \
                                generate_script(
                                    video_subject, video_length,
                                    video_language, cfg)
                        st.session_state.gen_step = 1
                    progress.progress(25)
                    status_box.success(
                        f"✅ Step 1 Done! Script ready "
                        f"({len(st.session_state.gen_script.split())} words)")

                    # Step 2
                    if st.session_state.gen_step < 2:
                        status_box.info(
                            "🎙️ Step 2/4 — Voice generate ho rahi hai...")
                        st.session_state.gen_voice = generate_voice(
                            st.session_state.gen_script,
                            selected_voice)
                        st.session_state.gen_step = 2
                    progress.progress(50)
                    status_box.success("✅ Step 2 Done! Voice ready!")

                    # Step 3
                    if st.session_state.gen_step < 3:
                        status_box.info(
                            "🖼️ Step 3/4 — Video clips fetch ho rahe hain...")
                        keyword = video_subject or \
                            " ".join(
                                st.session_state.gen_script.split()[:3])
                        video_urls = fetch_pexels_videos(
                            keyword, 5, cfg)
                        if not video_urls:
                            st.warning("⚠️ Pexels clips nahi mile!")
                            st.stop()
                        clip_paths = []
                        for i, url in enumerate(video_urls[:5]):
                            p = download_video(url, i)
                            clip_paths.append(p)
                        st.session_state.gen_clips = clip_paths
                        st.session_state.gen_step = 3
                    progress.progress(75)
                    status_box.success(
                        f"✅ Step 3 Done! "
                        f"{len(st.session_state.gen_clips)} clips ready!")

                    # Step 4
                    if st.session_state.gen_step < 4:
                        status_box.info(
                            "🎬 Step 4/4 — Video compose ho rahi hai... "
                            "⏳ 2-3 min lagenge, page mat band karo!")
                        output_path = compose_video(
                            st.session_state.gen_clips,
                            st.session_state.gen_voice,
                            video_aspect, font_size,
                            subtitle_color, subtitle_position,
                            st.session_state.gen_script)
                        st.session_state.gen_output = output_path
                        st.session_state.gen_step = 4
                    progress.progress(100)
                    status_box.success("🎉 Video ban gayi!")

                    # Script expander
                    with st.expander("📝 Generated Script dekho"):
                        st.write(st.session_state.gen_script)

                    # Video + Download
                    if os.path.exists(st.session_state.gen_output):
                        with open(
                                st.session_state.gen_output, "rb") as f:
                            video_bytes = f.read()
                        st.video(video_bytes)
                        st.download_button(
                            label="⬇️ Video Download Karo",
                            data=video_bytes,
                            file_name=f"brainreel_{video_subject[:20]}.mp4",
                            mime="video/mp4",
                            use_container_width=True
                        )

                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")
                    st.warning(
                        "💡 Connecting aaya tha? "
                        "Dobara Generate dabao — "
                        "wahan se continue hoga!")

elif page == "⚙️ Settings":
    st.markdown("## ⚙️ Settings")
    st.caption("API keys aur models configure karo.")
    s1, s2 = st.tabs(["🔑 API Keys", "🤖 Models"])

    with s1:
        st.markdown('<div class="card-title">🔑 API Keys</div>',
                    unsafe_allow_html=True)
        openai_key = st.text_input(
            "OpenAI API Key",
            value=cfg.get("openai_api_key", ""),
            type="password", placeholder="sk-...")
        st.markdown(
            f'<span class="key-status '
            f'{"key-set" if cfg.get("openai_api_key") else "key-empty"}">'
            f'{"✓ Set hai" if cfg.get("openai_api_key") else "○ Empty"}'
            f'</span>', unsafe_allow_html=True)

        openrouter_key = st.text_input(
            "OpenRouter API Key",
            value=cfg.get("openrouter_api_key", ""),
            type="password", placeholder="sk-or-...")
        st.markdown(
            f'<span class="key-status '
            f'{"key-set" if cfg.get("openrouter_api_key") else "key-empty"}">'
            f'{"✓ Set hai" if cfg.get("openrouter_api_key") else "○ Empty"}'
            f'</span>', unsafe_allow_html=True)

        pexels_key = st.text_input(
            "Pexels API Key",
            value=cfg.get("pexels_api_key", ""),
            type="password", placeholder="Pexels key")
        st.markdown(
            f'<span class="key-status '
            f'{"key-set" if cfg.get("pexels_api_key") else "key-empty"}">'
            f'{"✓ Set hai" if cfg.get("pexels_api_key") else "○ Empty"}'
            f'</span>', unsafe_allow_html=True)

        pixabay_key = st.text_input(
            "Pixabay API Key",
            value=cfg.get("pixabay_api_key", ""),
            type="password", placeholder="Pixabay key")
        st.markdown(
            f'<span class="key-status '
            f'{"key-set" if cfg.get("pixabay_api_key") else "key-empty"}">'
            f'{"✓ Set hai" if cfg.get("pixabay_api_key") else "○ Empty"}'
            f'</span>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save API Keys"):
            cfg["openai_api_key"] = openai_key
            cfg["openrouter_api_key"] = openrouter_key
            cfg["pexels_api_key"] = pexels_key
            cfg["pixabay_api_key"] = pixabay_key
            if save_config(cfg):
                st.success("✅ Keys save ho gayi!")
                st.rerun()
            else:
                st.error("❌ Save nahi hua!")

    with s2:
        st.markdown('<div class="card-title">🤖 Model Settings</div>',
                    unsafe_allow_html=True)
        providers = ["OpenAI", "OpenRouter", "DeepSeek",
                     "Moonshot", "Google Gemini", "Ollama"]
        current_provider = cfg.get("llm_provider", "OpenAI")
        provider_idx = providers.index(current_provider) \
            if current_provider in providers else 0
        llm_provider = st.selectbox(
            "LLM Provider", providers, index=provider_idx)

        model_options = MODEL_LISTS.get(
            llm_provider, ["Custom (type below)"])
        saved_model = cfg.get("model_name", "")

        if saved_model in model_options:
            default_idx = model_options.index(saved_model)
        else:
            default_idx = len(model_options) - 1

        selected_model = st.selectbox(
            "Model (List se chuno)",
            model_options, index=default_idx)

        if selected_model == "Custom (type below)":
            model_name = st.text_input(
                "Ya khud likho (Custom Model)",
                value=saved_model
                if saved_model not in model_options else "",
                placeholder="koi bhi naya model likho")
        else:
            model_name = selected_model

        base_url = st.text_input(
            "Base URL (optional)",
            value=cfg.get("base_url", ""),
            placeholder="Default ke liye khali chhodo")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Model Settings"):
            cfg["llm_provider"] = llm_provider
            cfg["model_name"] = model_name
            cfg["base_url"] = base_url
            if save_config(cfg):
                st.success("✅ Model settings save ho gayi!")
                st.rerun()
            else:
                st.error("❌ Save nahi hua!")

elif page == "📜 History":
    st.markdown("## 📜 Video History")
    st.info("🎬 Abhi koi video nahi — Generate Video pe jao!")

elif page == "📊 Analytics":
    st.markdown("## 📊 Analytics")
    c1, c2, c3 = st.columns(3)
    with c1: st.metric("Videos Generated", "0")
    with c2: st.metric("Total Duration", "0 min")
    with c3: st.metric("Success Rate", "—")
    st.info("📊 Videos generate hone ke baad stats ayenge!")
