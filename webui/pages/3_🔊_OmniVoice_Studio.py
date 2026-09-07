"""
OmniVoice Studio — integration page.

Launches and links to OmniVoice Studio (port 3900), the open-source
ElevenLabs alternative with voice cloning, video dubbing, and 646 languages.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import streamlit as st

# ── Paths ─────────────────────────────────────────────────────────────────────
root_dir = Path(__file__).resolve().parents[2]
# OmniVoice may be at ~/OmniVoice (installed by the upstream installer)
# or at omnivoice-studio/ inside this project root.
_candidate_dirs = [
    Path.home() / "OmniVoice",
    root_dir / "omnivoice-studio",
]
OVS_DIR = next((d for d in _candidate_dirs if (d / "backend" / "main.py").exists()), _candidate_dirs[0])
OVS_PORT = 3900
OVS_URL  = f"http://127.0.0.1:{OVS_PORT}"
OVS_LOG  = root_dir / "omnivoice-studio.log"

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="OmniVoice Studio",
    page_icon="🔊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
.feature-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 10px;
    text-align: center;
}
.feature-card h3 { margin: 0 0 6px; font-size: 1.1rem; }
.feature-card p  { font-size: .82rem; color: #8b949e; margin: 0; }
.launch-box {
    background: #0d2040;
    border: 1px solid #1f6feb;
    border-radius: 12px;
    padding: 24px 28px;
    text-align: center;
    margin: 20px 0;
}
.status-dot-green { color: #3fb950; font-size: 1.2rem; }
.status-dot-red   { color: #f85149; font-size: 1.2rem; }
</style>
""", unsafe_allow_html=True)

# ── Helper: check if OVS backend is alive ─────────────────────────────────────
def _ovs_alive() -> bool:
    try:
        with urllib.request.urlopen(f"{OVS_URL}/system/info", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False

def _ovs_installed() -> bool:
    return (OVS_DIR / "backend" / "main.py").exists() and (OVS_DIR / ".venv" / "bin" / "uvicorn").exists()

def _start_ovs() -> bool:
    """Launch OmniVoice Studio backend. Returns True when healthy."""
    venv_uvicorn = OVS_DIR / ".venv" / "bin" / "uvicorn"
    if not venv_uvicorn.exists():
        return False
    subprocess.Popen(
        [str(venv_uvicorn), "main:app",
         "--app-dir", "backend",
         "--host", "127.0.0.1", "--port", str(OVS_PORT)],
        cwd=str(OVS_DIR),
        stdout=open(str(OVS_LOG), "a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    for _ in range(60):
        time.sleep(1)
        if _ovs_alive():
            return True
    return False

# ── Header ────────────────────────────────────────────────────────────────────
col_title, col_status = st.columns([3, 1])
with col_title:
    st.title("🔊 OmniVoice Studio")
    st.caption(
        "Open-source ElevenLabs alternative — voice cloning, video dubbing, "
        "audiobook editor, and real-time dictation across **646 languages**."
    )

with col_status:
    alive = _ovs_alive()
    if alive:
        st.markdown('<span class="status-dot-green">●</span> **Running**', unsafe_allow_html=True)
        if st.button("⟳ Restart", use_container_width=True):
            subprocess.run(["pkill", "-f", f"port {OVS_PORT}"], check=False)
            subprocess.run(["pkill", "-f", "omnivoice"], check=False)
            time.sleep(1)
            with st.spinner("Restarting OmniVoice…"):
                _start_ovs()
            st.rerun()
    else:
        st.markdown('<span class="status-dot-red">●</span> **Offline**', unsafe_allow_html=True)

st.divider()

# ── Not installed guard ───────────────────────────────────────────────────────
if not _ovs_installed():
    st.error(
        "OmniVoice Studio is not installed.\n\n"
        "Run the following from the project root:\n"
        "```bash\n"
        "git clone https://github.com/debpalash/OmniVoice-Studio.git omnivoice-studio\n"
        "cd omnivoice-studio && bash scripts/install.sh\n"
        "```"
    )
    st.stop()

# ── Launch box ────────────────────────────────────────────────────────────────
if not alive:
    st.markdown("""
<div class="launch-box">
  <h2>🔊 OmniVoice Studio is not running</h2>
  <p style="color:#8b949e">Click below to start the backend. The web UI will open automatically.</p>
</div>
""", unsafe_allow_html=True)

    launch_col, open_col = st.columns(2)
    with launch_col:
        if st.button("▶️ Start OmniVoice Studio", type="primary", use_container_width=True):
            with st.spinner("Starting OmniVoice Studio… (first start may take 30s)"):
                ok = _start_ovs()
            if ok:
                st.success("OmniVoice Studio is running!")
                time.sleep(0.5)
                st.rerun()
            else:
                st.error(f"Failed to start. Check log: `{OVS_LOG}`")
    with open_col:
        st.markdown(
            f'<a href="{OVS_URL}" target="_blank">'
            '<button style="width:100%;padding:8px 0;background:#21262d;border:1px solid #30363d;'
            'border-radius:6px;color:#e6edf3;cursor:pointer;font-size:14px;">🌐 Open in Browser</button>'
            "</a>",
            unsafe_allow_html=True,
        )
else:
    # ── Running — show launch panel + iframe ──────────────────────────────────
    btn_col, _ = st.columns([1, 3])
    with btn_col:
        st.link_button("🌐 Open OmniVoice in new tab", OVS_URL, type="primary", use_container_width=True)

    st.markdown("### Live preview")
    st.markdown(
        f'<iframe src="{OVS_URL}" width="100%" height="800" '
        'style="border:1px solid #30363d;border-radius:10px;" '
        'allow="microphone; camera"></iframe>',
        unsafe_allow_html=True,
    )

st.divider()

# ── Feature grid ─────────────────────────────────────────────────────────────
st.markdown("### What you can do with OmniVoice Studio")

fc = st.columns(4)
features = [
    ("🎙️ Voice Cloning",      "3-second clip → mirror any voice across 646 languages, zero-shot."),
    ("🎨 Voice Design",        "Gender, age, accent, pitch, speed, emotion — dial it in precisely."),
    ("🎬 Video Dubbing",       "YouTube URL or file → transcribe → translate → re-voice → MP4."),
    ("📖 Audiobook Editor",    "Import text, EPUB, or PDF. Auto-chapter, loudnorm, export .m4b."),
    ("🎭 Multi-Voice Stories", "Assign different voices per line. Preview full cast, export all."),
    ("⌨️ Dictation Widget",    "⌘+⇧+Space from any app. Transcribes, auto-pastes, disappears."),
    ("🔊 Vocal Isolation",     "Separate vocals from background noise for clean source audio."),
    ("🌐 646 Languages",       "Broadest language coverage of any open-source TTS system."),
]
for i, (title, desc) in enumerate(features):
    with fc[i % 4]:
        st.markdown(
            f'<div class="feature-card"><h3>{title}</h3><p>{desc}</p></div>',
            unsafe_allow_html=True,
        )

st.divider()

# ── Setup / Troubleshooting ───────────────────────────────────────────────────
with st.expander("⚙️ Setup & Troubleshooting"):
    st.markdown(f"""
### First-time setup

```bash
# From MoneyPrinterTurbo project root:
cd omnivoice-studio
bash scripts/install.sh
```

This installs Python deps (via `uv`) and the required TTS engines.
Takes ~2 minutes on first run; subsequent starts are instant.

### Manual start

```bash
cd omnivoice-studio
bash scripts/run.sh
# → opens http://127.0.0.1:{OVS_PORT} in your browser
```

### Logs

```
{OVS_LOG}
```

### Ports

| Service | Port |
|---------|------|
| MoneyPrinterTurbo WebUI | 8080 |
| MPT TTS Service (edge-tts) | 8090 |
| **OmniVoice Studio** | **{OVS_PORT}** |

### Source

[github.com/debpalash/OmniVoice-Studio](https://github.com/debpalash/OmniVoice-Studio) · AGPL-3.0
""")
