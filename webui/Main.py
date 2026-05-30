import streamlit as st
import os
import tempfile
import json
import subprocess

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
        cfg.get("openai_api_key") or cfg.get("openrouter_api_key"))
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
            st.text_area("Your Script",
                         placeholder="Yahan script likho...",
                         height=180)
        col1, col2 = st.columns(2)
        with col1:
            st.selectbox("Language",
                ["English", "Urdu", "Hindi", "Arabic", "Chinese"])
        with col2:
            st.selectbox("Video Length",
                ["30 seconds", "1 minute", "3 minutes", "5 minutes"])

    with tab2:
        st.markdown('<div class="card-title">🎨 Visual Style</div>',
                    unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            st.selectbox("Aspect Ratio",
                ["9:16 (Vertical / TikTok)",
                 "16:9 (Horizontal / YouTube)"])
        with col2:
            st.selectbox("Video Source",
                ["Pexels (Free)", "Pixabay (Free)", "Local Files"])
        st.markdown("**Subtitle Settings**")
        col3, col4 = st.columns(2)
        with col3:
            st.slider("Font Size", 30, 100, 60)
        with col4:
            st.selectbox("Position", ["Bottom", "Center", "Top"])
        st.color_picker("Subtitle Color", "#FFFFFF")

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
        if st.button("🚀 Generate Video", use_container_width=True):
            if not video_subject:
                st.error("⚠️ Video topic enter karo pehle!")
            else:
                with st.status(
                        "🎬 Generating...", expanded=True) as status:
                    st.write("📝 Script likh raha hai...")
                    st.write("🖼️ Clips fetch ho rahe hain...")
                    st.write("🔊 Voiceover ban raha hai...")
                    st.write("🎬 Video compose ho rahi hai...")
                    status.update(label="✅ Done!",
                                  state="complete", expanded=False)
                st.success("🎉 Video ready!")
                st.info("💡 Abhi demo mode — API keys Settings mein daalo!")

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
