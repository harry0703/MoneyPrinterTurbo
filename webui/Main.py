import streamlit as st
import os, json, subprocess, requests, re, asyncio
import time as time_module
import edge_tts

# ── Colab / Jupyter / Streamlit async compatibility ──────────────────────────
try:
    import nest_asyncio
    nest_asyncio.apply()
except (ImportError, ValueError):
    # ValueError = uvloop.Loop can't be patched — that's fine.
    # uvloop already handles concurrency natively, no patch needed.
    pass

def _run_async(coro):
    """Run async coroutine safely from sync code.
    Works with: standard asyncio, uvloop, Streamlit, Colab — all cases."""
    try:
        asyncio.get_running_loop()
        # A loop IS already running (uvloop / Streamlit / Jupyter).
        # Cannot call run_until_complete here — use a thread instead.
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result()
    except RuntimeError:
        # No running loop — safe to call asyncio.run directly.
        return asyncio.run(coro)
# ─────────────────────────────────────────────────────────────────────────────

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except:
        return {"openai_api_key":"","openrouter_api_key":"",
                "pexels_api_key":"","pixabay_api_key":"",
                "llm_provider":"OpenRouter",
                "model_name":"mistralai/mistral-7b-instruct:free",
                "base_url":"https://openrouter.ai/api/v1",
                "user_name":"Creator"}

def save_config(data):
    try:
        with open(CONFIG_PATH,"w") as f:
            json.dump(data,f,indent=2)
        return True
    except: return False

def clean_script(s):
    s = re.sub(r'\[.*?\]','',s)
    s = re.sub(r'\*{1,2}(.*?)\*{1,2}',r'\1',s)
    s = re.sub(r'#+\s*','',s)
    s = re.sub(r'\n+',' ',s)
    return re.sub(r'\s+',' ',s).strip()

def get_rate_pitch(speed, deep):
    rate = int((speed - 50) * 1)
    rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
    pitch = int((50 - deep) * 0.8)
    pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
    return rate_str, pitch_str

async def _async_preview(voice, text, tmp, rate_str, pitch_str):
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
    await communicate.save(tmp)

def run_preview(voice, text, speed=50, deep=50):
    ts = int(time_module.time())
    tmp = f"/tmp/prev_{ts}.mp3"
    rate_str, pitch_str = get_rate_pitch(speed, deep)
    _run_async(_async_preview(voice, text, tmp, rate_str, pitch_str))
    with open(tmp, "rb") as f:
        return f.read()

async def _async_generate_voice(text, voice, vp, vtt, rate_str, pitch_str):
    """Generate TTS audio and a word-by-word VTT (one word per cue, exact timing)."""
    communicate = edge_tts.Communicate(text, voice, rate=rate_str, pitch=pitch_str)
    word_boundaries = []          # list of {word, start_sec, dur_sec}

    with open(vp, "wb") as audio_file:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_file.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # Microsoft returns offset/duration in 100-nanosecond ticks
                word_boundaries.append({
                    "word":  chunk["text"],
                    "start": chunk["offset"]   / 10_000_000,
                    "dur":   chunk["duration"] / 10_000_000,
                })

    # Write VTT: one word per cue, no overlap, minimum 100 ms display
    if word_boundaries and vtt:
        with open(vtt, "w", encoding="utf-8") as f:
            f.write("WEBVTT\n\n")
            for i, wb in enumerate(word_boundaries):
                s = wb["start"]
                e = s + wb["dur"]
                # End just before next word to prevent screen overlap
                if i + 1 < len(word_boundaries):
                    e = min(e, word_boundaries[i + 1]["start"] - 0.05)
                e = max(e, s + 0.10)     # at least 100 ms visible
                sm = f"{int(s // 60):02d}:{s % 60:06.3f}"
                em = f"{int(e // 60):02d}:{e % 60:06.3f}"
                f.write(f"{sm} --> {em}\n{wb['word']}\n\n")

def generate_voice(script, voice, speed=50, deep=50):
    clean = clean_script(script)
    ts = int(time_module.time())
    vp = f"/tmp/voice_{ts}.mp3"
    vtt = f"/tmp/subs_{ts}.vtt"
    rate_str, pitch_str = get_rate_pitch(speed, deep)
    _run_async(_async_generate_voice(clean, voice, vp, vtt, rate_str, pitch_str))
    return vp, (vtt if os.path.exists(vtt) else None)

def vtt_to_sec(t):
    try:
        t = t.strip().replace(',','.')
        p = t.split(':')
        if len(p)==3: return float(p[0])*3600+float(p[1])*60+float(p[2])
        elif len(p)==2: return float(p[0])*60+float(p[1])
    except: return 0.0
    return 0.0

def sec_to_srt(t):
    h,m,s,ms=int(t//3600),int((t%3600)//60),int(t%60),int((t%1)*1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def parse_vtt(vtt_path):
    words = []
    try:
        with open(vtt_path,'r',encoding='utf-8') as f:
            content = f.read()
        for block in content.strip().split('\n\n'):
            lines = [l.strip() for l in block.split('\n') if l.strip()]
            for i, line in enumerate(lines):
                if '-->' in line:
                    parts = line.split('-->')
                    start = vtt_to_sec(parts[0])
                    end = vtt_to_sec(parts[1].split()[0])
                    texts = lines[i+1:]
                    text = re.sub(r'<[^>]+>','', ' '.join(texts)).strip()
                    if text: words.append((start, end, text))
                    break
    except: pass
    return words

def get_duration(path):
    r = subprocess.run(["ffprobe","-v","quiet","-show_entries",
                        "format=duration","-of","csv=p=0",path],
                       capture_output=True, text=True)
    try: return float(r.stdout.strip())
    except: return 30.0

def generate_bg_music(duration, style, volume):
    if style == "No Music" or volume == 0: return None
    path = "/tmp/bg_music.aac"
    vol  = round((volume / 100.0) * 0.25, 4)  # 0-100 → 0.0-0.25 amplitude
    dur  = int(duration) + 5

    freq_map = {
        "Calm":      [("220","0.5"),("330","0.3"),("440","0.2")],
        "Upbeat":    [("330","0.5"),("440","0.3"),("550","0.2")],
        "Cinematic": [("110","0.6"),("165","0.3"),("220","0.1")],
        "Random":    [("220","0.5"),("275","0.3"),("330","0.2")],
    }
    tones = freq_map.get(style, freq_map["Calm"])

    inputs_cmd, labels, weights = [], [], []
    for i, (freq, w) in enumerate(tones):
        inputs_cmd += ["-f","lavfi","-i",
                       f"sine=frequency={freq}:duration={dur}:sample_rate=44100"]
        labels.append(f"[{i}:a]")
        weights.append(w)

    mix_filter = (
        "".join(labels)
        + f"amix=inputs={len(tones)}:weights={chr(39)}{'|'.join(weights)}{chr(39)}:normalize=0,"
        + f"volume={vol}[bgout]"
    )
    cmd = ["ffmpeg","-y"] + inputs_cmd + [
        "-filter_complex", mix_filter,
        "-map","[bgout]","-t",str(dur),
        "-c:a","aac","-ar","44100","-b:a","128k", path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if os.path.exists(path) and os.path.getsize(path) > 500:
        return path
    if result.returncode != 0:
        print(f"[BG Music Warning] {result.stderr[-300:]}")
    return None

def fetch_pexels(keyword, count, cfg):
    key = cfg.get("pexels_api_key") or os.environ.get("PEXELS_API_KEY","")
    r = requests.get("https://api.pexels.com/videos/search",
        headers={"Authorization":key},
        params={"query":keyword,"per_page":count,"orientation":"portrait","size":"medium"},
        timeout=15)
    r.raise_for_status()
    urls = []
    for v in r.json().get("videos",[]):
        for f in v.get("video_files",[]):
            if f.get("quality") in ["hd","sd"] and f.get("file_type")=="video/mp4":
                urls.append(f["link"]); break
    return urls

def download_clip(url, idx):
    path = f"/tmp/clip_{idx}.mp4"
    r = requests.get(url, timeout=60, stream=True)
    with open(path,"wb") as f:
        for chunk in r.iter_content(8192): f.write(chunk)
    return path

def compose_video(clips, voice_path, vtt_path, aspect,
                  font_size, color, position, script, bg_style, bg_vol, max_dur_secs=None):
    out = "/tmp/final.mp4"
    W,H = (1080,1920) if "9:16" in aspect else (1920,1080)
    # ── B2 FIX: enforce user-selected duration cap ───────────────────────────
    voice_dur = get_duration(voice_path)
    if max_dur_secs and voice_dur > max_dur_secs:
        trimmed = "/tmp/voice_trimmed.mp3"
        subprocess.run(["ffmpeg","-y","-i",voice_path,
                        "-t",str(max_dur_secs),"-c:a","copy",trimmed],
                       capture_output=True)
        if os.path.exists(trimmed) and os.path.getsize(trimmed) > 500:
            voice_path = trimmed
    dur = get_duration(voice_path)
    if max_dur_secs: dur = min(dur, max_dur_secs)   # hard cap
    # ─────────────────────────────────────────────────────────────────────────
    cdur = dur / max(len(clips), 1)

    scaled = []
    for i, clip in enumerate(clips):
        o = f"/tmp/sc_{i}.mp4"
        cd = get_duration(clip)
        loop = ["-stream_loop", str(int(cdur/max(cd,0.1))+2)] if cd < cdur else []
        subprocess.run(["ffmpeg","-y"]+loop+["-i",clip,"-t",str(cdur),
            "-vf",f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
            "-c:v","libx264","-preset","ultrafast","-an",o], capture_output=True)
        if os.path.exists(o): scaled.append(o)

    clist = "/tmp/cl.txt"
    with open(clist,"w") as f:
        for c in scaled: f.write(f"file '{c}'\n")
    cout = "/tmp/co.mp4"
    subprocess.run(["ffmpeg","-y","-f","concat","-safe","0","-i",clist,
                    "-t",str(dur),"-c:v","libx264","-preset","ultrafast",cout],
                   capture_output=True)

    words = parse_vtt(vtt_path) if vtt_path and os.path.exists(vtt_path) else []
    srt = "/tmp/ws.srt"
    hex_c = color.lstrip('#')
    try:
        r2,g2,b2 = int(hex_c[:2],16),int(hex_c[2:4],16),int(hex_c[4:],16)
        ass_c = f"&H00{b2:02X}{g2:02X}{r2:02X}&"
    except: ass_c = "&H00FFFFFF&"
    align = {"Bottom":2,"Center":5,"Top":8}.get(position, 2)

    if words:
        with open(srt,'w',encoding='utf-8') as f:
            for i,(s,e,w) in enumerate(words,1):
                f.write(f"{i}\n{sec_to_srt(s)} --> {sec_to_srt(e)}\n{w}\n\n")
    else:
        clean = clean_script(script)
        all_words = clean.split()
        chunk_size = 4
        chunks = [' '.join(all_words[j:j+chunk_size])
                  for j in range(0, len(all_words), chunk_size)]
        tpc = dur / max(len(chunks), 1)
        with open(srt,'w',encoding='utf-8') as f:
            for i, ch in enumerate(chunks, 1):
                s2, e2 = i*tpc-tpc, i*tpc
                f.write(f"{i}\n{sec_to_srt(s2)} --> {sec_to_srt(e2)}\n{ch}\n\n")

    sub_f = (f"subtitles={srt}:force_style='"
             f"FontSize={font_size},"
             f"PrimaryColour={ass_c},"
             f"OutlineColour=&H00000000&,"
             f"BackColour=&H80000000&,"
             f"Bold=1,Outline=2,Shadow=1,"
             f"MarginV=50,"
             f"MaxLines=1,"
             f"Alignment={align}'")

    bg = generate_bg_music(dur, bg_style, bg_vol)

    if bg:
        cmd = ["ffmpeg","-y","-i",cout,"-i",voice_path,"-i",bg,
               "-t",str(dur),
               "-filter_complex",
               "[1:a]volume=1.0[va];[2:a]volume=0.5[ba];[va][ba]amix=inputs=2:duration=first:normalize=0[aout]",
               "-map","0:v","-map","[aout]",
               "-vf",sub_f,
               "-c:v","libx264","-preset","ultrafast","-c:a","aac",out]
    else:
        cmd = ["ffmpeg","-y","-i",cout,"-i",voice_path,
               "-t",str(dur),"-map","0:v","-map","1:a",
               "-vf",sub_f,
               "-c:v","libx264","-preset","ultrafast","-c:a","aac",out]

    subprocess.run(cmd, capture_output=True)

    if not os.path.exists(out) or os.path.getsize(out) < 1000:
        if bg:
            subprocess.run(["ffmpeg","-y","-i",cout,"-i",voice_path,"-i",bg,
                "-t",str(dur),
                "-filter_complex","[1:a]volume=1.0[va];[2:a]volume=0.5[ba];[va][ba]amix=inputs=2:duration=first:normalize=0[aout]",
                "-map","0:v","-map","[aout]",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",out], capture_output=True)
        else:
            subprocess.run(["ffmpeg","-y","-i",cout,"-i",voice_path,
                "-t",str(dur),"-map","0:v","-map","1:a",
                "-c:v","libx264","-preset","ultrafast","-c:a","aac",out], capture_output=True)
    return out

def generate_script_api(topic, duration, language, cfg):
    wc = {"30 seconds":"40-50","1 minute":"90-110",
          "3 minutes":"380-420","5 minutes":"600-650"}.get(duration,"90-110")
    lang = {"English":"English","Urdu":"Urdu","Hindi":"Hindi",
            "Arabic":"Arabic","Chinese":"Chinese"}.get(language,"English")
    prompt = f"""Write a faceless YouTube video script about: {topic}
Language: {lang}. Word count: EXACTLY {wc} words.
STRICT RULES: Pure narration only. NO [brackets], NO markdown, NO headers.
Start immediately with a strong hook."""
    key = cfg.get("openrouter_api_key") or os.environ.get("OPENROUTER_API_KEY","")
    model = cfg.get("model_name") or "mistralai/mistral-7b-instruct:free"
    base = cfg.get("base_url") or "https://openrouter.ai/api/v1"
    resp = requests.post(f"{base}/chat/completions",
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json",
                 "HTTP-Referer":"https://huggingface.co","X-Title":"BrainReel"},
        json={"model":model,"messages":[{"role":"user","content":prompt}],"max_tokens":800},
        timeout=60)
    resp.raise_for_status()
    return clean_script(resp.json()["choices"][0]["message"]["content"])

ETA_MAP = {"30 seconds":"~2 min","1 minute":"~3 min",
           "3 minutes":"~7 min","5 minutes":"~15 min"}

# Compose-step estimated seconds (longest step)
COMPOSE_ETA = {"30 seconds":90,"1 minute":150,
               "3 minutes":360,"5 minutes":600}

def _fmt_time(secs):
    """Format seconds → '1m 23s' or '45s'."""
    secs = max(0, int(secs))
    return f"{secs//60}m {secs%60}s" if secs >= 60 else f"{secs}s"

# Hard duration cap in seconds — enforced via ffmpeg trim
DURATION_SECS = {"30 seconds":30,"1 minute":60,
                 "3 minutes":180,"5 minutes":300}

VOICE_MAP = {
    "en-US-AriaNeural — English Female 🇺🇸":"en-US-AriaNeural",
    "en-US-GuyNeural — English Male 🇺🇸":"en-US-GuyNeural",
    "ur-PK-UzmaNeural — Urdu Female 🇵🇰":"ur-PK-UzmaNeural",
    "ur-PK-AsadNeural — Urdu Male 🇵🇰":"ur-PK-AsadNeural",
    "hi-IN-SwaraNeural — Hindi Female 🇮🇳":"hi-IN-SwaraNeural",
    "hi-IN-MadhurNeural — Hindi Male 🇮🇳":"hi-IN-MadhurNeural",
    "ar-SA-ZariyahNeural — Arabic Female 🇸🇦":"ar-SA-ZariyahNeural",
    "zh-CN-XiaoxiaoNeural — Chinese Female 🇨🇳":"zh-CN-XiaoxiaoNeural",
}
PREVIEW_TEXTS = {
    "en-US-AriaNeural":"Hello! I am Aria. I will be the voice of your video.",
    "en-US-GuyNeural":"Hello! I am Guy. I will be the voice of your video.",
    "ur-PK-UzmaNeural":"السلام علیکم! میں آپ کی ویڈیو کی آواز ہوں۔",
    "ur-PK-AsadNeural":"السلام علیکم! میں آپ کی ویڈیو کی آواز ہوں۔",
    "hi-IN-SwaraNeural":"नमस्ते! मैं आपके वीडियो की आवाज़ हूँ।",
    "hi-IN-MadhurNeural":"नमस्ते! मैं आपके वीडियो की आवाज़ हूँ।",
    "ar-SA-ZariyahNeural":"مرحبا! أنا صوت الفيديو الخاص بك.",
    "zh-CN-XiaoxiaoNeural":"你好！我是你视频的声音。",
}
MODEL_LISTS = {
    "OpenAI":["gpt-4o","gpt-4o-mini","gpt-4-turbo","gpt-3.5-turbo","Custom (type below)"],
    "OpenRouter":["deepseek/deepseek-chat","deepseek/deepseek-r1",
                  "google/gemini-flash-1.5","google/gemini-pro-1.5",
                  "meta-llama/llama-3.1-8b-instruct:free",
                  "meta-llama/llama-3.3-70b-instruct",
                  "mistralai/mixtral-8x7b-instruct",
                  "mistralai/mistral-7b-instruct:free",
                  "anthropic/claude-3-haiku","anthropic/claude-3.5-sonnet",
                  "qwen/qwen-2.5-72b-instruct",
                  "microsoft/phi-3-medium-128k-instruct:free",
                  "Custom (type below)"],
    "DeepSeek":["deepseek-chat","deepseek-reasoner","Custom (type below)"],
    "Moonshot":["moonshot-v1-8k","moonshot-v1-32k","moonshot-v1-128k","Custom (type below)"],
    "Google Gemini":["gemini-1.5-flash","gemini-1.5-pro","gemini-2.0-flash","Custom (type below)"],
    "Ollama":["llama3","llama3.1","mistral","qwen2.5","deepseek-r1","Custom (type below)"],
}

st.set_page_config(page_title="BrainReel",page_icon="🎬",
                   layout="wide",initial_sidebar_state="collapsed")

cfg = load_config()

# ══════════════════════════════════════
# WELCOME SCREEN
# ══════════════════════════════════════
if "welcome_done" not in st.session_state:
    st.session_state.welcome_done = False

if not st.session_state.welcome_done:
    user_name = cfg.get("user_name", "Creator")

    # ── Welcome page CSS ─────────────────────────────────────────────────────
    st.markdown("""<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;700;900&family=Orbitron:wght@700;900&display=swap');
.stApp{background:#0B0F1A!important}
.main .block-container{padding:8px 16px!important;max-width:100%!important}
#MainMenu,footer,header{visibility:hidden!important}
/* ── X close button ── */
div[data-testid="stButton"].welcome-x > button{
    background:rgba(255,255,255,0.06)!important;
    border:1px solid rgba(255,255,255,0.12)!important;
    color:#888!important;border-radius:50%!important;
    width:38px!important;height:38px!important;
    min-width:38px!important;padding:0!important;
    font-size:18px!important;font-weight:400!important;
    letter-spacing:0!important;text-transform:none!important;
    line-height:1!important;transition:all 0.2s!important;
    box-shadow:none!important;}
div[data-testid="stButton"].welcome-x > button:hover{
    background:rgba(255,60,60,0.15)!important;
    border-color:rgba(255,80,80,0.4)!important;
    color:#ff6060!important;}
/* ── Enter button ── */
div[data-testid="stButton"].welcome-enter > button{
    background:linear-gradient(135deg,#1a3a6b,#2F80FF)!important;
    color:white!important;border:none!important;
    border-radius:30px!important;padding:15px 40px!important;
    font-size:13px!important;font-weight:700!important;
    letter-spacing:4px!important;text-transform:uppercase!important;
    box-shadow:0 0 30px #2F80FF50,0 4px 20px #2F80FF30!important;
    transition:all 0.3s!important;width:100%!important;}
div[data-testid="stButton"].welcome-enter > button:hover{
    box-shadow:0 0 45px #2F80FF80,0 6px 30px #2F80FF50!important;
    transform:translateY(-2px)!important;}
/* pulse animation on BRAINREEL */
@keyframes brPulse{
    0%,100%{text-shadow:0 0 30px #2F80FF90,0 0 60px #2F80FF40;}
    50%{text-shadow:0 0 50px #2F80FFcc,0 0 90px #2F80FF70,0 0 120px #2F80FF30;}}
.br-title{animation:brPulse 3s ease-in-out infinite;}
</style>""", unsafe_allow_html=True)

    # ── Top bar: X close button ───────────────────────────────────────────────
    _, _, x_col = st.columns([12, 1, 1])
    with x_col:
        st.markdown('<div class="welcome-x">', unsafe_allow_html=True)
        if st.button("✕", key="welcome_x"):
            st.session_state.welcome_done = True
            st.rerun()
        st.markdown('</div>', unsafe_allow_html=True)

    # ── Welcome HTML ──────────────────────────────────────────────────────────
    st.markdown(f"""
<div style='min-height:75vh;background:#0B0F1A;display:flex;flex-directi
