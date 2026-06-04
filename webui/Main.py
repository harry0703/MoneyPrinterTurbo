import streamlit as st
import os, json, subprocess, requests, re
import time as time_module

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

def run_preview(voice, text, speed=50, deep=50):
    ts = int(time_module.time())
    tmp = f"/tmp/prev_{ts}.mp3"
    rate_str, pitch_str = get_rate_pitch(speed, deep)
    cmd = ["edge-tts","--voice",voice,"--text",text,"--write-media",tmp]
    if rate_str != "+0%": cmd.append(f"--rate={rate_str}")
    if pitch_str != "+0Hz": cmd.append(f"--pitch={pitch_str}")
    subprocess.run(cmd, check=True, capture_output=True)
    with open(tmp,"rb") as f:
        return f.read()

def generate_voice(script, voice, speed=50, deep=50):
    clean = clean_script(script)
    ts = int(time_module.time())
    vp = f"/tmp/voice_{ts}.mp3"
    vtt = f"/tmp/subs_{ts}.vtt"
    rate_str, pitch_str = get_rate_pitch(speed, deep)
    cmd = ["edge-tts","--voice",voice,"--text",clean,
           "--write-media",vp,"--write-subtitles",vtt]
    if rate_str != "+0%": cmd.append(f"--rate={rate_str}")
    if pitch_str != "+0Hz": cmd.append(f"--pitch={pitch_str}")
    subprocess.run(cmd, check=True, capture_output=True)
    return vp, vtt if os.path.exists(vtt) else None

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
    path = "/tmp/bg.aac"
    vol = (volume / 100.0) * 0.06
    dur = duration + 5
    exprs = {
        "Calm":    f"{vol}*sin(2*PI*t*220)+{vol*0.5}*sin(2*PI*t*330)+{vol*0.3}*sin(2=PI*t*440)",
        "Upbeat":  f"{vol}*sin(2=PI*t*330)+{vol*0.7}*sin(2*PI*t*440)+{vol*0.5}*sin(2*PI*t*550)",
        "Cinematic":f"{vol}*sin(2*PI*t*110)+{vol*0.4}*sin(2*PI*t*165)+{vol*0.2}*sin(2*PI*t*220)",
        "Random":  f"{vol}*sin(2*PI*t*220)+{vol*0.4}*sin(2*PI*t*275)+{vol*0.3}*sin(2*PI*t*330)",
    }
    expr = exprs.get(style, exprs["Calm"])
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i",
                    f"aevalsrc={expr}:s=44100:d={dur}",
                    "-c:a","aac",path], capture_output=True)
    return path if os.path.exists(path) else None

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
                  font_size, color, position, script, bg_style, bg_vol):
    out = "/tmp/final.mp4"
    W,H = (1080,1920) if "9:16" in aspect else (1920,1080)
    dur = get_duration(voice_path)
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
             f"Alignment={align}'")

    bg = generate_bg_music(dur, bg_style, bg_vol)

    if bg:
        cmd = ["ffmpeg","-y","-i",cout,"-i",voice_path,"-i",bg,
               "-t",str(dur),
               "-filter_complex",
               "[1:a]volume=1.0[v];[2:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first[a]",
               "-map","0:v","-map","[a]",
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
                "-filter_complex","[1:a]volume=1.0[v];[2:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first[a]",
                "-map","0:v","-map","[a]",
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

# ── PAGE CONFIG ──
st.set_page_config(page_title="BrainReel",page_icon="🎬",
                   layout="wide",initial_sidebar_state="collapsed")

cfg = load_config()

# ══════════════════════════════════════
# WELCOME SCREEN (FIXED RAW HTML BUG & DESIGN UPGRADE)
# ══════════════════════════════════════
if "welcome_done" not in st.session_state:
    st.session_state.welcome_done = False

if not st.session_state.welcome_done:
    user_name = cfg.get("user_name","Creator")
    
    # Custom Global CSS for Welcome Page
    st.markdown("""
<style>
.stApp { background: #060913 !important; }
.main .block-container { padding: 0 !important; max-width: 100% !important; }
#MainMenu, footer, header { visibility: hidden !important; }
.stButton>button {
    background: linear-gradient(135deg, #7c3aed, #2563eb) !important;
    color: white !important;
    border: none !important;
    border-radius: 14px !important;
    padding: 15px 45px !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    letter-spacing: 3px !important;
    text-transform: uppercase !important;
    box-shadow: 0 8px 25px rgba(124, 58, 237, 0.4) !important;
    transition: all 0.3s ease-out !important;
    width: 100% !important;
}
.stButton>button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 12px 30px rgba(124, 58, 237, 0.6) !important;
}
</style>""", unsafe_allow_html=True)

    # Clean HTML block without any markdown indentation spaces
    st.markdown(f"""
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;900&family=Orbitron:wght@800&display=swap" rel="stylesheet">
<div style="min-height: 78vh; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 40px 20px; font-family: 'Montserrat', sans-serif;">
    <div style="background: rgba(255, 255, 255, 0.03); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 24px; padding: 50px 40px; max-width: 600px; width: 100%; box-shadow: 0 20px 50px rgba(0,0,0,0.4);">
        <div style="letter-spacing: 10px; font-size: 13px; font-weight: 400; color: #a78bfa; margin-bottom: 8px;">WELCOME TO</div>
        <div style="letter-spacing: 4px; font-size: 46px; font-weight: 900; background: linear-gradient(90deg, #a78bfa, #60a5fa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-family: 'Orbitron', sans-serif; margin-bottom: 20px; filter: drop-shadow(0 2px 10px rgba(124,58,237,0.3));">BRAINREEL</div>
        <div style="width: 80px; height: 2px; background: linear-gradient(90deg, #7c3aed, #2563eb); margin: 0 auto 24px;"></div>
        <div style="font-size: 11px; color: #9ca3af; letter-spacing: 4px; text-transform: uppercase; margin-bottom: 35px; font-weight: 500;">Make Your Life Fast With AI</div>
        <div style="font-size: 22px; color: #f3f4f6; margin-bottom: 10px; font-weight: 400;">Welcome back, <span style="color: #60a5fa; font-weight: 600;">{user_name}</span> 👋</div>
        <div style="font-size: 14px; color: #9ca3af; margin-bottom: 25px; letter-spacing: 0.5px;">🎬 AI-Powered Faceless Video Engine</div>
        <div style="font-size: 11px; color: rgba(255,255,255,0.25); letter-spacing: 2px; text-transform: uppercase;">OpenRouter &nbsp;•&nbsp; Pexels &nbsp;•&nbsp; Edge-TTS &nbsp;•&nbsp; FFmpeg</div>
    </div>
</div>
<div style="text-align: center; font-size: 10px; color: #4b5563; letter-spacing: 2px; text-transform: uppercase; padding-bottom: 20px; font-family: 'Montserrat', sans-serif;">
    Revamped &amp; Engineered — Ahsan Raza
</div>
""", unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        if st.button("✨  ENTER  BRAINREEL  ✨", use_container_width=True):
            st.session_state.welcome_done = True
            st.rerun()
    st.stop()

# ══════════════════════════════════════
# MAIN APP CSS
# ══════════════════════════════════════
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;background-color:#0e0e0e;color:#f0f0f0;}
#MainMenu{visibility:hidden;}footer{visibility:hidden;}
header{visibility:visible!important;}
[data-testid="stAppDeployButton"]{display:none!important;}
button[data-testid="collapsedControl"]{
    visibility:visible!important;display:flex!important;opacity:1!important;
    background:linear-gradient(135deg,#7c3aed,#2563eb)!important;
    border-radius:8px!important;border:none!important;
    width:40px!important;height:40px!important;
    box-shadow:0 4px 15px rgba(124,58,237,0.5)!important;}
button[data-testid="collapsedControl"] svg{fill:white!important;}
button[data-testid="expandedControl"]{
    visibility:visible!important;display:flex!important;opacity:1!important;
    background:rgba(255,255,255,0.1)!important;
    border:1px solid rgba(255,255,255,0.2)!important;
    border-radius:8px!important;width:36px!important;height:36px!important;}
button[data-testid="expandedControl"] svg{fill:#f0f0f0!important;}
section[data-testid="stSidebar"]{
    background:linear-gradient(180deg,#1a1a2e 0%,#16213e 100%);
    border-right:1px solid #2a2a4a;}
.brand-logo{text-align:center;padding:20px 0 10px 0;}
.brand-title{font-size:28px;font-weight:700;
    background:linear-gradient(90deg,#a78bfa,#60a5fa);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;margin:0;}
.brand-sub{font-size:12px;color:#888;margin-top:4px;}
.card-title{font-size:14px;font-weight:600;color:#a78bfa;
    margin-bottom:12px;text-transform:uppercase;letter-spacing:1px;}
.stButton>button{
    background:linear-gradient(90deg,#7c3aed,#2563eb);
    color:white;border:none;border-radius:8px;
    font-weight:600;padding:10px 24px;width:100%;transition:opacity 0.2s;}
.stButton>button:hover{opacity:0.85;color:white;}
.stTextInput>div>div>input,
.stTextArea>div>div>textarea,
.stSelectbox>div>div{
    background:#0e0e1a!important;border:1px solid #2a2a4a!important;
    border-radius:8px!important;color:#f0f0f0!important;}
.stTabs [data-baseweb="tab-list"]{
    background:#1a1a2e;border-radius:10px;padding:4px;gap:4px;}
.stTabs [data-baseweb="tab"]{
    background:transparent;border-radius:8px;
    color:#888;font-weight:600;padding:14px 22px;font-size:15px;}
.stTabs [aria-selected="true"]{
    background:linear-gradient(90deg,#7c3aed,#2563eb)!important;color:white!important;}
.badge{display:inline-block;padding:3px 10px;border-radius:20px;
    font-size:11px;font-weight:600;}
.badge-ready{background:#064e3b;color:#34d399;}
.badge-warn{background:#451a03;color:#fb923c;}
.section-header{font-size:11px;text-transform:uppercase;
    letter-spacing:2px;color:#555;margin:20px 0 8px 0;}
.key-status{font-size:12px;padding:4px 10px;border-radius:6px;
    margin-top:4px;display:inline-block;}
.key-set{background:#064e3b;color:#34d399;}
.key-empty{background:#1a1a2e;color:#555;}

/* HIGH VISIBILITY WATERMARK CSS FIX */
.watermark{font-size:10px;color:#94a3b8;letter-spacing:2px;
    text-transform:uppercase;text-align:center;font-weight:600;
    padding:12px 0 4px;border-top:1px solid #2d3748;}

div[data-testid="stRadio"] label{font-size:16px!important;padding:10px 8px!important;}
</style>
""",unsafe_allow_html=True)
