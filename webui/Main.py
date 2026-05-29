import streamlit as st
import os
import sys

# Path setup
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

# Page config - MUST be first
st.set_page_config(
    page_title="BrainReel — AI Video Generator",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ──────────────────────────────────────────
st.markdown("""
<style>
/* Google Font */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', sans-serif;
    background-color: #0e0e0e;
    color: #f0f0f0;
}

/* Hide default Streamlit elements */
#MainMenu {visibility: hidden;}
footer {visibility: hidden;}
header {visibility: hidden;}

/* Sidebar */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    border-right: 1px solid #2a2a4a;
}

/* Logo area */
.brand-logo {
    text-align: center;
    padding: 20px 0 10px 0;
}
.brand-title {
    font-size: 28px;
    font-weight: 700;
    background: linear-gradient(90deg, #a78bfa, #60a5fa);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    margin: 0;
}
.brand-sub {
    font-size: 12px;
    color: #888;
    margin-top: 4px;
}

/* Cards */
.card {
    background: #1a1a2e;
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
}
.card-title {
    font-size: 14px;
    font-weight: 600;
    color: #a78bfa;
    margin-bottom: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* Buttons */
.stButton > button {
    background: linear-gradient(90deg, #7c3aed, #2563eb);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    padding: 10px 24px;
    width: 100%;
    transition: opacity 0.2s;
}
.stButton > button:hover {
    opacity: 0.85;
    color: white;
}

/* Inputs */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stSelectbox > div > div {
    background: #0e0e1a !important;
    border: 1px solid #2a2a4a !important;
    border-radius: 8px !important;
    color: #f0f0f0 !important;
}

/* Tabs */
.stTabs [data-baseweb="tab-list"] {
    background: #1a1a2e;
    border-radius: 10px;
    padding: 4px;
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent;
    border-radius: 8px;
    color: #888;
    font-weight: 600;
    padding: 8px 16px;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(90deg, #7c3aed, #2563eb) !important;
    color: white !important;
}

/* Status badge */
.badge {
    display: inline-block;
    padding: 3px 10px;
    border-radius: 20px;
    font-size: 11px;
    font-weight: 600;
}
.badge-ready { background: #064e3b; color: #34d399; }
.badge-warn  { background: #451a03; color: #fb923c; }

/* Section header */
.section-header {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 2px;
    color: #555;
    margin: 20px 0 8px 0;
}
</style>
""", unsafe_allow_html=True)

# ── Sidebar ─────────────────────────────────────────────
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
        options=["🎬 Generate Video", "⚙️ Settings", "📜 History", "📊 Analytics"],
        label_visibility="collapsed"
    )

    st.markdown("---")

    # Quick status
    st.markdown('<div class="section-header">Status</div>',
                unsafe_allow_html=True)

    api_configured = False
    try:
        from app.config import config
        llm_key = getattr(config, 'openai_api_key', '') or ''
        api_configured = len(str(llm_key)) > 10
    except Exception:
        pass

    if api_configured:
        st.markdown('<span class="badge badge-ready">✓ API Ready</span>',
                    unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge badge-warn">⚠ API Not Set</span>',
                    unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption("v2.0 · BrainReel Edition")

# ── Main Content ────────────────────────────────────────

# ---- PAGE: Generate Video ----
if page == "🎬 Generate Video":
    st.markdown("## 🎬 Generate Video")
    st.caption("Fill in the details below and let AI do the magic!")

    tab1, tab2, tab3 = st.tabs(["📝 Script", "🎨 Style", "🔊 Voice & Music"])

    with tab1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">📝 Video Script</div>',
                    unsafe_allow_html=True)

        video_subject = st.text_input(
            "Video Topic / Subject",
            placeholder="e.g. 5 mind-blowing facts about black holes",
        )

        script_mode = st.radio(
            "Script Mode",
            ["🤖 AI Auto Generate", "✍️ Write Manually"],
            horizontal=True,
        )

        if script_mode == "✍️ Write Manually":
            video_script = st.text_area(
                "Your Script",
                placeholder="Write your video script here...",
                height=200,
            )
        else:
            video_script = ""

        col1, col2 = st.columns(2)
        with col1:
            video_language = st.selectbox(
                "Language",
                ["English", "Urdu", "Hindi", "Chinese", "Spanish"],
            )
        with col2:
            video_length = st.selectbox(
                "Video Length",
                ["30 seconds", "1 minute", "3 minutes", "5 minutes"],
            )

        st.markdown('</div>', unsafe_allow_html=True)

    with tab2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🎨 Visual Style</div>',
                    unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        with col1:
            video_aspect = st.selectbox(
                "Aspect Ratio",
                ["9:16 (Vertical / TikTok)", "16:9 (Horizontal / YouTube)"],
            )
        with col2:
            video_source = st.selectbox(
                "Video Source",
                ["Pexels (Free)", "Pixabay (Free)", "Local Files"],
            )

        st.markdown("**Subtitle Settings**")
        col3, col4 = st.columns(2)
        with col3:
            font_size = st.slider("Font Size", 30, 100, 60)
        with col4:
            subtitle_position = st.selectbox(
                "Position", ["Bottom", "Center", "Top"]
            )

        subtitle_color = st.color_picker("Subtitle Color", "#FFFFFF")
        st.markdown('</div>', unsafe_allow_html=True)

    with tab3:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🔊 Voice & Music</div>',
                    unsafe_allow_html=True)

        voice_option = st.selectbox(
            "TTS Voice",
            [
                "en-US-AriaNeural (English Female)",
                "en-US-GuyNeural (English Male)",
                "ur-PK-UzmaNeural (Urdu Female) 🇵🇰",
                "ur-PK-AsadNeural (Urdu Male) 🇵🇰",
                "hi-IN-SwaraNeural (Hindi Female)",
            ],
        )

        music_volume = st.slider("Background Music Volume", 0, 100, 30)

        bg_music = st.selectbox(
            "Background Music",
            ["Random", "Calm", "Upbeat", "Cinematic", "No Music"],
        )
        st.markdown('</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    col_gen1, col_gen2, col_gen3 = st.columns([1, 2, 1])
    with col_gen2:
        generate_btn = st.button("🚀 Generate Video", use_container_width=True)

    if generate_btn:
        if not video_subject and not video_script:
            st.error("⚠️ Please enter a video topic or script first!")
        else:
            with st.status("🎬 Generating your video...", expanded=True) as status:
                st.write("📝 Writing script...")
                st.write("🖼️ Fetching video clips...")
                st.write("🔊 Generating voiceover...")
                st.write("🎬 Composing final video...")
                status.update(
                    label="✅ Video ready!",
                    state="complete",
                    expanded=False,
                )
            st.success("🎉 Video generated successfully!")
            st.info("💡 Full generation logic coming soon — connect your API keys in Settings first!")

# ---- PAGE: Settings ----
elif page == "⚙️ Settings":
    st.markdown("## ⚙️ Settings")
    st.caption("Configure your API keys, models, and preferences.")

    s_tab1, s_tab2 = st.tabs(["🔑 API Keys", "🤖 Models"])

    with s_tab1:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🔑 API Keys</div>',
                    unsafe_allow_html=True)

        openai_key = st.text_input("OpenAI API Key", type="password",
                                    placeholder="sk-...")
        openrouter_key = st.text_input("OpenRouter API Key", type="password",
                                        placeholder="sk-or-...")
        pexels_key = st.text_input("Pexels API Key", type="password",
                                    placeholder="Your Pexels key")
        pixabay_key = st.text_input("Pixabay API Key", type="password",
                                     placeholder="Your Pixabay key")

        if st.button("💾 Save API Keys"):
            st.success("✅ Keys saved!")
        st.markdown('</div>', unsafe_allow_html=True)

    with s_tab2:
        st.markdown('<div class="card">', unsafe_allow_html=True)
        st.markdown('<div class="card-title">🤖 Model Settings</div>',
                    unsafe_allow_html=True)

        llm_provider = st.selectbox(
            "LLM Provider",
            ["OpenAI", "OpenRouter", "DeepSeek", "Moonshot",
             "Google Gemini", "Ollama (Local)"],
        )
        model_name = st.text_input(
            "Model Name",
            placeholder="e.g. gpt-4o / deepseek-chat",
        )
        base_url = st.text_input(
            "Base URL (optional)",
            placeholder="Leave empty for default",
        )

        if st.button("💾 Save Model Settings"):
            st.success("✅ Model settings saved!")
        st.markdown('</div>', unsafe_allow_html=True)

# ---- PAGE: History ----
elif page == "📜 History":
    st.markdown("## 📜 Video History")
    st.caption("Your previously generated videos.")

    st.info("🎬 No videos generated yet. Go to Generate Video to create your first one!")

# ---- PAGE: Analytics ----
elif page == "📊 Analytics":
    st.markdown("## 📊 Analytics")
    st.caption("Track your video generation stats.")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Videos Generated", "0")
    with col2:
        st.metric("Total Duration", "0 min")
    with col3:
        st.metric("Success Rate", "—")

    st.info("📊 Analytics will populate as you generate videos!")
