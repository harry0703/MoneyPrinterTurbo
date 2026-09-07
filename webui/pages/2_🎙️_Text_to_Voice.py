"""
Text-to-Voice Studio — powered by the local TTS service (tts-service/).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import streamlit as st

# ── Project root ──────────────────────────────────────────────────────────────
root_dir = Path(__file__).resolve().parents[2]
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

TTS_BASE     = "http://localhost:8090"
TTS_STORE    = root_dir / "tts-service" / "storage"
TTS_DIR      = root_dir / "tts-service"
TTS_LOG      = root_dir / "tts-service.log"

# ── TTS service launcher ──────────────────────────────────────────────────────

def _tts_venv_bin() -> Path | None:
    """Return the bin/ dir of the best available TTS venv."""
    for name in ("venv311", "venv"):
        p = TTS_DIR / name / "bin" / "uvicorn"
        if p.exists():
            return p.parent
    return None

def _start_tts_service() -> bool:
    """Launch the TTS service in the background. Returns True if it comes up."""
    bin_dir = _tts_venv_bin()
    if not bin_dir:
        return False
    env = {**os.environ, "TTS_ENGINE": os.environ.get("TTS_ENGINE", "edge_tts")}
    subprocess.Popen(
        [str(bin_dir / "uvicorn"), "app.main:app",
         "--host", "0.0.0.0", "--port", "8090", "--log-level", "warning"],
        cwd=str(TTS_DIR),
        env=env,
        stdout=open(str(TTS_LOG), "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    # Wait up to 12 s for it to respond
    for _ in range(24):
        time.sleep(0.5)
        if _tts_alive():
            return True
    return False

def _tts_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{TTS_BASE}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Voice Studio",
    page_icon="🎙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* Full-width audio player */
audio { width: 100% !important; border-radius: 8px; }

/* Preset card grid */
.preset-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 8px;
    cursor: pointer;
    transition: border-color .15s;
}
.preset-card:hover { border-color: #58a6ff; }
.preset-card.selected { border-color: #1f6feb; background: #0d2040; }
.preset-name  { font-weight: 600; font-size: .95rem; }
.preset-desc  { font-size: .78rem; color: #8b949e; margin-top: 3px; }
.preset-tags  { margin-top: 5px; }
.tag {
    display: inline-block;
    background: #21262d;
    border: 1px solid #30363d;
    border-radius: 20px;
    padding: 1px 8px;
    font-size: .7rem;
    color: #8b949e;
    margin-right: 3px;
}
.bookmark-star { font-size: 1.1rem; cursor: pointer; }
.section-label {
    font-size: .7rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #6e7681;
    margin: 12px 0 6px;
}
.result-box {
    background: #0d1117;
    border: 1px solid #21262d;
    border-radius: 10px;
    padding: 16px 18px;
    margin-top: 10px;
}
</style>
""", unsafe_allow_html=True)

# ── Session state defaults ────────────────────────────────────────────────────
for k, v in {
    "bookmarks": [],          # list of preset IDs
    "selected_preset": None,  # currently chosen preset ID
    "short_result": None,
    "lf_result": None,
    "compare_results": [],
    "export_folder": str(Path.home() / "Desktop" / "Voice Studio"),
    "sidebar_previews": {},   # pid -> {"audio_url": ..., "lang": ...}
    "sidebar_preview_lang": "en",
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ── API helpers ───────────────────────────────────────────────────────────────

def _get(path: str, timeout: int = 3):
    try:
        with urllib.request.urlopen(f"{TTS_BASE}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None

def _post(path: str, payload: dict, timeout: int = 300):
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{TTS_BASE}{path}", data=data,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as e:
        return {"error": str(e)}

def _audio_path(audio_url: str) -> Path | None:
    rel  = audio_url.removeprefix("/storage/")
    path = TTS_STORE / rel
    return path if path.exists() else None

def _save_to_folder(src: Path, folder: str, filename: str) -> Path | None:
    try:
        dest = Path(folder).expanduser().resolve()
        dest.mkdir(parents=True, exist_ok=True)
        out = dest / filename
        shutil.copy2(src, out)
        return out
    except Exception as e:
        st.error(f"Save failed: {e}")
        return None

# ── Cached preset fetch ───────────────────────────────────────────────────────

@st.cache_data(ttl=60)
def fetch_presets():
    data = _get("/presets")
    return data.get("presets", []) if data else []

@st.cache_data(ttl=300)
def fetch_preset_detail(pid: str):
    return _get(f"/presets/{pid}")

# ── Helpers ───────────────────────────────────────────────────────────────────

CATEGORY_LABELS = {
    "meditation_male":    "🧘 Meditation · Male",
    "meditation_female":  "🧘 Meditation · Female",
    "radio_narrator":     "📻 Radio & Narrator",
    "audiobook_narrator": "📚 Audiobook",
    "documentary_narration": "🎬 Documentary",
    "elearning":          "🎓 E-Learning",
    "commercial":         "💼 Commercial",
    "luxury_brand":       "✨ Luxury Brand",
    "customer_support":   "🎧 Customer Support",
    "children_story":     "🧸 Children's Story",
    "podcast_intro":      "🎙 Podcast",
    "app_onboarding":     "📱 App Onboarding",
}

LANGS   = {"en": "🇺🇸 English", "es": "🇪🇸 Spanish", "fr": "🇫🇷 French"}
FORMATS = {"wav": "WAV (lossless)", "mp3": "MP3 (compressed)"}

def category_label(cat: str) -> str:
    return CATEGORY_LABELS.get(cat, cat.replace("_", " ").title())

def render_audio_result(result: dict, fmt: str, filename: str, key_prefix: str = ""):
    """Render the inline player + download + save-to-folder controls."""
    if not result or "error" in result or result.get("status") != "completed":
        err = (result or {}).get("error") or (result or {}).get("detail") or "Unknown error."
        st.error(f"Generation failed: {err}")
        return

    dur    = result.get("duration_seconds", 0)
    cached = result.get("cached", False)
    chunks = result.get("chunks")

    parts = [f"✅ {dur:.1f}s"]
    if chunks:
        parts.append(f"{chunks} chunks")
    if cached:
        parts.append("cached ♻️")
    st.success("  ·  ".join(parts))

    fpath = _audio_path(result.get("audio_url", ""))
    if not fpath:
        st.info(f"Server path: `{result.get('audio_url')}`")
        return

    audio_bytes = fpath.read_bytes()
    mime = "audio/mpeg" if fmt == "mp3" else "audio/wav"

    st.markdown('<p class="section-label">Preview</p>', unsafe_allow_html=True)
    st.audio(audio_bytes, format=mime)

    dl_col, save_col = st.columns([1, 2])
    with dl_col:
        st.download_button(
            f"⬇️ Download {fmt.upper()}", data=audio_bytes,
            file_name=filename, mime=mime,
            use_container_width=True, key=f"dl_{key_prefix}",
        )
    with save_col:
        folder = st.session_state.export_folder
        if st.button("💾 Save to folder", use_container_width=True, key=f"save_{key_prefix}"):
            saved = _save_to_folder(fpath, folder, filename)
            if saved:
                st.success(f"Saved → `{saved}`")

# ═══════════════════════════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════════════════════════

header_col, status_col = st.columns([3, 1])
with header_col:
    st.title("🎙️ Voice Studio")
    st.caption("Natural, emotional, multilingual speech — meditations, audiobooks, radio, onboarding.")

with status_col:
    health = _get("/health")

    # ── Auto-start if offline ─────────────────────────────────────────────────
    if not health:
        with st.spinner("Starting TTS service…"):
            started = _start_tts_service()
        if started:
            health = _get("/health")
        else:
            st.error("🔴 TTS Service offline")
            has_venv = _tts_venv_bin() is not None
            if has_venv:
                if st.button("▶️ Start TTS Service", type="primary", use_container_width=True):
                    with st.spinner("Starting…"):
                        ok = _start_tts_service()
                    if ok:
                        st.success("Started!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Could not start. Check `tts-service.log`.")
                st.caption(f"Log: `{TTS_LOG}`")
            else:
                st.caption("No TTS venv found. Run `./start.sh` from the terminal.")
            st.stop()

    # ── Service is up ─────────────────────────────────────────────────────────
    if health:
        engine  = health.get("engine", "?")
        is_mock = engine == "mock"
        if is_mock:
            st.warning("🟡 Mock engine\n\nSilent audio only.")
        else:
            st.success(f"🟢 Live · **{engine}**")

        if st.button("⟳ Restart", use_container_width=True, help="Restart TTS service"):
            subprocess.run(["pkill", "-f", "uvicorn app.main"], check=False)
            time.sleep(1)
            with st.spinner("Restarting…"):
                _start_tts_service()
            st.rerun()

st.divider()

# ═══════════════════════════════════════════════════════════════════════════════
# SIDEBAR — Preset browser + folder
# ═══════════════════════════════════════════════════════════════════════════════

with st.sidebar:
    st.markdown("## 🎤 Voice Presets")

    # ── Folder picker ─────────────────────────────────────────────────────────
    with st.expander("📁 Export folder", expanded=False):
        folder_input = st.text_input(
            "Save generated audio to:",
            value=st.session_state.export_folder,
            placeholder="~/Desktop/Voice Studio",
            label_visibility="collapsed",
        )
        st.session_state.export_folder = folder_input

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("🏠 Desktop", use_container_width=True):
                st.session_state.export_folder = str(Path.home() / "Desktop" / "Voice Studio")
                st.rerun()
        with col_b:
            if st.button("📂 Documents", use_container_width=True):
                st.session_state.export_folder = str(Path.home() / "Documents" / "Voice Studio")
                st.rerun()

        resolved = Path(st.session_state.export_folder).expanduser()
        if resolved.exists():
            st.caption(f"✅ `{resolved}`")
        else:
            st.caption(f"📁 Will be created: `{resolved}`")

    st.markdown("---")

    # ── Bookmarks ─────────────────────────────────────────────────────────────
    if st.session_state.bookmarks:
        st.markdown("### ⭐ Bookmarked")
        all_presets_flat = fetch_presets()
        preset_map = {p["id"]: p for p in all_presets_flat}

        for bid in st.session_state.bookmarks:
            p = preset_map.get(bid, {})
            if not p:
                continue
            bc1, bc2 = st.columns([4, 1])
            with bc1:
                selected = st.session_state.selected_preset == bid
                label = ("▶ " if selected else "") + p.get("name", bid)
                if st.button(label, key=f"bm_{bid}", use_container_width=True):
                    st.session_state.selected_preset = bid
                    st.rerun()
            with bc2:
                if st.button("✕", key=f"unbm_{bid}", help="Remove bookmark"):
                    st.session_state.bookmarks.remove(bid)
                    st.rerun()

        st.markdown("---")

    # ── Sidebar preview language ──────────────────────────────────────────────
    sb_prev_lang = st.selectbox(
        "Preview language",
        list(LANGS.keys()),
        format_func=lambda c: LANGS[c],
        key="sidebar_preview_lang_select",
        index=list(LANGS.keys()).index(st.session_state.sidebar_preview_lang),
    )
    if sb_prev_lang != st.session_state.sidebar_preview_lang:
        # Clear cached previews when language changes so they re-generate
        st.session_state.sidebar_previews = {}
        st.session_state.sidebar_preview_lang = sb_prev_lang

    # ── Category filter ───────────────────────────────────────────────────────
    presets_data = fetch_presets()
    categories   = sorted({p.get("category", "") for p in presets_data})
    cat_options  = ["All categories"] + [category_label(c) for c in categories]
    cat_rev      = {category_label(c): c for c in categories}

    selected_cat_label = st.selectbox(
        "Filter by category",
        cat_options,
        label_visibility="collapsed",
    )
    filter_cat = cat_rev.get(selected_cat_label)

    # ── Search ────────────────────────────────────────────────────────────────
    search_q = st.text_input("🔍 Search presets", placeholder="meditation, morgan freeman style, radio…", label_visibility="collapsed")

    # ── Voice aliases (searches that map to specific presets) ─────────────────
    _VOICE_ALIASES = {
        "morgan freeman": "cinematic_elder_narrator",
        "morgan":         "cinematic_elder_narrator",
        "attenborough":   "cinematic_elder_narrator",
        "deep voice":     "cinematic_elder_narrator",
        "gravitas":       "cinematic_elder_narrator",
        "james earl":     "cinematic_elder_narrator",
        "oprah":          "warm_female_meditation",
    }

    def _matches_preset(p: dict, q: str) -> bool:
        if not q:
            return True
        ql = q.strip().lower()
        # Check alias map
        alias_id = _VOICE_ALIASES.get(ql)
        if alias_id and p.get("id") == alias_id:
            return True
        # Substring match against name + description + tags
        searchable = (
            p.get("name", "") + " " +
            p.get("description", "") + " " +
            " ".join(p.get("tags", []))
        ).lower()
        return ql in searchable

    # ── Preset list ───────────────────────────────────────────────────────────
    visible = [
        p for p in presets_data
        if (not filter_cat or p.get("category") == filter_cat)
        and _matches_preset(p, search_q)
    ]

    # Show alias hint if search matched a known person name
    if search_q:
        _alias_hit = _VOICE_ALIASES.get(search_q.strip().lower())
        if _alias_hit:
            st.info(
                "🎭 Real-person voice imitation is blocked for safety.\n\n"
                "Showing the closest safe alternative instead.",
                icon="ℹ️",
            )

    st.markdown(f'<p class="section-label">{len(visible)} voices</p>', unsafe_allow_html=True)

    for p in visible:
        pid       = p["id"]
        is_sel    = st.session_state.selected_preset == pid
        is_bm     = pid in st.session_state.bookmarks
        tags_html = "".join(f'<span class="tag">{t}</span>' for t in (p.get("tags") or [])[:4])
        lang_badges = "".join(
            f'<span class="tag">{LANGS.get(lg, lg).split()[0]}</span>'
            for lg in (p.get("supported_languages") or ["en"])
        )

        card_class = "preset-card selected" if is_sel else "preset-card"
        st.markdown(f"""
<div class="{card_class}">
  <div class="preset-name">{p.get('name', pid)}</div>
  <div class="preset-desc">{p.get('description','')[:90]}…</div>
  <div class="preset-tags">{tags_html}&nbsp;{lang_badges}</div>
</div>
""", unsafe_allow_html=True)

        btn_col, prev_col, bm_col = st.columns([4, 2, 1])
        with btn_col:
            btn_label = "✓ Selected" if is_sel else "Select"
            btn_type  = "primary" if is_sel else "secondary"
            if st.button(btn_label, key=f"sel_{pid}", type=btn_type, use_container_width=True):
                st.session_state.selected_preset = pid
                st.rerun()
        with prev_col:
            if st.button("▶ Preview", key=f"prev_{pid}", use_container_width=True):
                with st.spinner("…"):
                    r = _post(f"/presets/{pid}/preview", {"language": sb_prev_lang})
                if r and r.get("audio_url"):
                    st.session_state.sidebar_previews[pid] = {
                        "audio_url": r["audio_url"],
                        "lang": sb_prev_lang,
                        "duration": r.get("duration_seconds", 0),
                        "cached": r.get("cached", False),
                    }
                else:
                    st.session_state.sidebar_previews[pid] = {"error": True}
                st.rerun()
        with bm_col:
            star = "⭐" if is_bm else "☆"
            if st.button(star, key=f"bm_toggle_{pid}", help="Bookmark this voice"):
                if is_bm:
                    st.session_state.bookmarks.remove(pid)
                else:
                    st.session_state.bookmarks.append(pid)
                st.rerun()

        # ── Inline audio player if preview was generated ──────────────────
        pv = st.session_state.sidebar_previews.get(pid)
        if pv:
            if pv.get("error"):
                st.caption("⚠️ Preview failed")
            else:
                fpath = _audio_path(pv["audio_url"])
                if fpath and fpath.exists():
                    cached_label = " ♻️" if pv.get("cached") else ""
                    st.audio(fpath.read_bytes(), format="audio/wav")
                    st.caption(f"{pv.get('duration',0):.1f}s · {LANGS.get(pv['lang'], pv['lang'])}{cached_label}")

# ═══════════════════════════════════════════════════════════════════════════════
# MAIN AREA — tabs
# ═══════════════════════════════════════════════════════════════════════════════

# ── Selected preset info bar ──────────────────────────────────────────────────
sel_pid = st.session_state.selected_preset
if sel_pid:
    detail = fetch_preset_detail(sel_pid)
    if detail:
        pi1, pi2, pi3, pi4 = st.columns([3, 1, 1, 1])
        with pi1:
            st.markdown(f"**Selected voice:** {detail.get('name', sel_pid)}")
            st.caption(f"_{detail.get('description','')[:120]}_")
        with pi2:
            st.metric("Speed", f"{detail.get('prosody',{}).get('speed',1.0):.2f}×")
        with pi3:
            st.metric("Warmth", f"{detail.get('emotional_profile',{}).get('warmth',0):.0%}")
        with pi4:
            st.metric("Stability", f"{detail.get('emotional_profile',{}).get('stability',0):.0%}")
        st.divider()
else:
    st.info("👈 **Select a voice** from the sidebar to get started.", icon="🎤")

# ── Language / format (shared) ────────────────────────────────────────────────
lf_col, fmt_col = st.columns(2)
with lf_col:
    language = st.selectbox("Language", list(LANGS.keys()), format_func=lambda c: LANGS[c])
with fmt_col:
    fmt = st.selectbox("Format", list(FORMATS.keys()), format_func=lambda f: FORMATS[f])

# ── Tabs ──────────────────────────────────────────────────────────────────────
tab_short, tab_long, tab_preview, tab_compare = st.tabs([
    "✂️  Short Clip",
    "📜  Long-form",
    "👁  Preview Voice",
    "⚖️  Compare Voices",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — SHORT CLIP
# ─────────────────────────────────────────────────────────────────────────────
with tab_short:
    st.markdown(
        "Add `<break time=\"2s\" />` or `<break time=\"500ms\" />` anywhere to insert pauses."
    )

    text = st.text_area(
        "Text",
        placeholder=(
            'Close your eyes. <break time="2s" />\n'
            'Take a slow, deep breath. <break time="1.5s" />\n'
            'You are exactly where you need to be.'
        ),
        height=200,
        label_visibility="collapsed",
    )

    with st.expander("⚙️  Emotion overrides (optional)", expanded=False):
        ov_col1, ov_col2, ov_col3, ov_col4 = st.columns(4)
        ov_warmth  = ov_col1.slider("Warmth",         0.0, 1.0, 0.80, 0.05, key="ov_w")
        ov_soft    = ov_col2.slider("Softness",        0.0, 1.0, 0.85, 0.05, key="ov_s")
        ov_expr    = ov_col3.slider("Expressiveness",  0.0, 1.0, 0.55, 0.05, key="ov_e")
        ov_stab    = ov_col4.slider("Stability",       0.0, 1.0, 0.90, 0.05, key="ov_st")
        ov_speed   = st.slider("Speed", 0.7, 1.4, 1.0, 0.05, key="ov_sp")
        use_overrides = st.toggle("Apply emotion overrides", value=False)

    go = st.button("🎙️ Generate clip", type="primary", disabled=not sel_pid and True)

    if go:
        if not text.strip():
            st.warning("Please enter some text.")
        elif not sel_pid:
            st.warning("Select a voice from the sidebar first.")
        else:
            payload = {
                "text": text, "language": language,
                "preset_id": sel_pid, "format": fmt,
            }
            if use_overrides:
                payload["override_settings"] = {
                    "warmth": ov_warmth, "softness": ov_soft,
                    "expressiveness": ov_expr, "stability": ov_stab,
                    "speed": ov_speed,
                }
            with st.spinner("Generating…"):
                result = _post("/speech/generate", payload)
            st.session_state.short_result = result
            st.session_state.short_fmt    = fmt

    if st.session_state.short_result:
        r = st.session_state.short_result
        f = st.session_state.get("short_fmt", fmt)
        fpath = _audio_path(r.get("audio_url", "")) if r and "audio_url" in r else None
        fname = fpath.name if fpath else f"clip.{f}"
        with st.container():
            st.markdown('<div class="result-box">', unsafe_allow_html=True)
            render_audio_result(r, f, fname, "short")
            st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — LONG-FORM
# ─────────────────────────────────────────────────────────────────────────────
with tab_long:
    st.markdown(
        "Use blank lines between paragraphs for natural pacing. "
        "Insert `<break time=\"3s\" />` for explicit pauses."
    )

    lf_title = st.text_input("Title", placeholder="Morning Calm Meditation", key="lf_title")

    lf_text = st.text_area(
        "Full script",
        placeholder=(
            "Find a comfortable position and close your eyes.\n\n"
            "<break time=\"3s\" />\n\n"
            "Take a slow breath in through the nose… hold… and release.\n\n"
            "<break time=\"2s\" />\n\n"
            "With every exhale, let the tension leave your body completely."
        ),
        height=300,
        label_visibility="collapsed",
    )

    ck1, ck2 = st.columns(2)
    max_chars = ck1.slider("Max chars per chunk", 200, 2000, 900, 50)
    pause_ms  = ck2.slider("Pause between chunks (ms)", 0, 2000, 650, 50)

    go_lf = st.button("🎙️ Generate narration", type="primary", key="go_lf")

    if go_lf:
        if not lf_title.strip():
            st.warning("Please enter a title.")
        elif not lf_text.strip():
            st.warning("Please enter a script.")
        elif not sel_pid:
            st.warning("Select a voice from the sidebar first.")
        else:
            with st.spinner("Generating — may take a minute for long scripts…"):
                result = _post("/speech/generate-long-form", {
                    "title": lf_title,
                    "text": lf_text,
                    "language": language,
                    "preset_id": sel_pid,
                    "format": fmt,
                    "chunking": {
                        "enabled": True,
                        "max_chars": max_chars,
                        "pause_between_chunks_ms": pause_ms,
                    },
                }, timeout=600)
            st.session_state.lf_result     = result
            st.session_state.lf_fmt        = fmt
            st.session_state.lf_title_out  = lf_title

    if st.session_state.lf_result:
        r  = st.session_state.lf_result
        f  = st.session_state.get("lf_fmt", fmt)
        t  = st.session_state.get("lf_title_out", "narration")
        fpath = _audio_path(r.get("audio_url", "")) if r and "audio_url" in r else None
        fname = fpath.name if fpath else f"{t}.{f}".replace(" ", "_").lower()
        with st.container():
            st.markdown('<div class="result-box">', unsafe_allow_html=True)
            render_audio_result(r, f, fname, "lf")
            st.markdown('</div>', unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — VOICE PREVIEW
# ─────────────────────────────────────────────────────────────────────────────
with tab_preview:
    if not sel_pid:
        st.info("Select a voice from the sidebar to preview it here.")
    else:
        detail = fetch_preset_detail(sel_pid)
        if detail:
            # Two-column layout: info left, audio right
            info_col, audio_col = st.columns([1, 1])

            with info_col:
                st.subheader(detail.get("name", sel_pid))
                st.caption(f"Category: **{category_label(detail.get('category',''))}**")
                st.markdown(detail.get("description", ""))

                tags = detail.get("tags", [])
                if tags:
                    st.markdown(" ".join(f"`{t}`" for t in tags))

                ep = detail.get("emotional_profile", {})
                if ep:
                    st.markdown("**Emotional profile**")
                    for field, val in ep.items():
                        st.progress(float(val), text=field.capitalize())

                pro = detail.get("prosody", {})
                if pro:
                    st.markdown("**Prosody**")
                    pcols = st.columns(2)
                    items = list(pro.items())
                    for i, (k, v) in enumerate(items):
                        pcols[i % 2].metric(k.replace("_", " ").title(), v)

            with audio_col:
                st.markdown("**Generate a preview sample**")
                sample_types = ["meditation", "narration", "documentary", "radio", "children", "commercial"]
                sample_type  = st.selectbox("Sample type", sample_types)
                prev_lang    = st.selectbox("Language", list(LANGS.keys()),
                                            format_func=lambda c: LANGS[c], key="prev_lang")

                if st.button("▶️ Generate preview", type="primary"):
                    with st.spinner("Generating preview…"):
                        result = _post(f"/presets/{sel_pid}/preview", {
                            "language": prev_lang,
                        })
                    if result and result.get("audio_url"):
                        fpath = _audio_path(result["audio_url"])
                        if fpath and fpath.exists():
                            cached_note = " · cached ♻️" if result.get("cached") else ""
                            st.audio(fpath.read_bytes(), format="audio/wav")
                            st.caption(
                                f"{result.get('duration_seconds', 0):.1f}s"
                                f" · {LANGS.get(prev_lang, prev_lang)}"
                                f"{cached_note}"
                            )
                            st.markdown(f"> _{result.get('sample_text', '')}_")
                        else:
                            st.error("Audio file not found on disk — check TTS service storage.")
                    else:
                        err = (result or {}).get("error") or (result or {}).get("detail") or "Unknown error"
                        st.error(f"Preview failed: {err}")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — COMPARE VOICES
# ─────────────────────────────────────────────────────────────────────────────
with tab_compare:
    st.markdown("Generate the same text with multiple voices side by side.")

    compare_text = st.text_area(
        "Text to compare",
        value="Welcome to your practice. Take a slow breath and feel yourself arrive.",
        height=100,
        key="compare_text",
    )

    all_presets   = fetch_presets()
    preset_options = {p["id"]: f"{p['name']}  —  {category_label(p.get('category',''))}"
                     for p in all_presets}

    _available_pids = set(preset_options.keys())
    _default_compare = (
        [st.session_state.selected_preset]
        if st.session_state.selected_preset in _available_pids
        else []
    )
    compare_ids = st.multiselect(
        "Select voices to compare (2–4)",
        options=list(preset_options.keys()),
        format_func=lambda pid: preset_options[pid],
        default=_default_compare,
        max_selections=4,
    )
    compare_lang = st.selectbox("Language", list(LANGS.keys()),
                                format_func=lambda c: LANGS[c], key="cmp_lang")

    if st.button("⚖️ Compare voices", type="primary", key="go_compare"):
        if len(compare_ids) < 2:
            st.warning("Select at least 2 voices to compare.")
        elif not compare_text.strip():
            st.warning("Enter some text first.")
        else:
            with st.spinner(f"Generating {len(compare_ids)} voice samples…"):
                result = _post("/presets/compare", {
                    "text": compare_text,
                    "language": compare_lang,
                    "preset_ids": compare_ids,
                })
            st.session_state.compare_results = (result or {}).get("results", [])
            st.session_state.compare_error   = (result or {}).get("error")

    if st.session_state.compare_error:
        st.error(f"Compare failed: {st.session_state.compare_error}")

    if st.session_state.compare_results:
        st.markdown("---")
        cols = st.columns(len(st.session_state.compare_results))
        for col, item in zip(cols, st.session_state.compare_results):
            pid   = item.get("preset_id", "?")
            pname = preset_options.get(pid, pid)
            with col:
                st.markdown(f"**{pname.split('—')[0].strip()}**")
                if item.get("status") == "completed":
                    fpath = _audio_path(item.get("audio_url", ""))
                    if fpath:
                        st.audio(fpath.read_bytes(),
                                 format="audio/mpeg" if fmt == "mp3" else "audio/wav")
                        st.caption(f"{item.get('duration_seconds',0):.1f}s")
                        st.download_button(
                            f"⬇️ {pid[:18]}",
                            data=fpath.read_bytes(),
                            file_name=fpath.name,
                            mime="audio/wav",
                            key=f"cmp_dl_{pid}",
                            use_container_width=True,
                        )
                else:
                    st.error(item.get("error") or "Failed")

# ═══════════════════════════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════════════════════════
st.divider()
with st.expander("ℹ️  Break tags · Voice safety · API docs"):
    st.markdown("""
### Break / pause tags
```
<break time="2.5s" />    ← 2.5 second silence
<break time="500ms" />   ← 500 millisecond silence
<pause time="1s" />      ← alias
```

### Voice safety
Real-person voice imitation is blocked. If you request a celebrity-style voice,
the service returns a safe descriptive alternative (e.g. "Morgan Freeman-style" →
`cinematic_elder_narrator`).

### API docs
[http://localhost:8090/docs](http://localhost:8090/docs)

### Supported languages
🇺🇸 English (`en`) · 🇪🇸 Spanish (`es`) · 🇫🇷 French (`fr`)
""")
