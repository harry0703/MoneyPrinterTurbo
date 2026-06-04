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
    rate = int((speed - 50) * 2)
    rate_str = f"+{rate}%" if rate >= 0 else f"{rate}%"
    pitch = int((50 - deep) * 1.5)
    pitch_str = f"+{pitch}Hz" if pitch >= 0 else f"{pitch}Hz"
    return rate_str, pitch_str

def run_preview(voice, text, speed=50, deep=50):
    ts = int(time_module.time())
    tmp = f"/tmp/prev_{ts}.mp3"
    rate_str, pitch_str = get_rate_pitch(speed, deep)
    cmd = ["edge-tts","--voice",voice,"--text",text,"--write-media",tmp]
    if rate_str != "+0%": cmd += ["--rate", rate_str]
    if pitch_str != "+0Hz": cmd += ["--pitch", pitch_str]
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
    if rate_str != "+0%": cmd += ["--rate", rate_str]
    if pitch_str != "+0Hz": cmd += ["--pitch", pitch_str]
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
                    
                    if text:
                        split_words = text.split()
                        num_words = len(split_words)
                        if num_words > 0:
                            total_d = end - start
                            w_dur = total_d / num_words
                            for idx, w in enumerate(split_words):
                                w_start = start + (idx * w_dur)
                                w_end = w_start + w_dur
                                words.append((w_start, w_end, w))
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
    vol = (volume / 100.0) * 0.25
    dur = duration + 5
    exprs = {
        "Calm":    "0.5*sin(2*PI*t*180)+0.3*sin(2*PI*t*240)",
        "Upbeat":  "0.4*sin(2*PI*t*280)+0.4*sin(2*PI*t*350)",
        "Cinematic":"0.6*sin(2*PI*t*120)+0.3*sin(2*PI*t*180)",
        "Random":  "0.4*sin(2*PI*t*200)+0.4*sin(2*PI*t*300)",
    }
    expr = exprs.get(style, exprs["Calm"])
    subprocess.run(["ffmpeg","-y","-f","lavfi","-i",
                    f"aevalsrc={expr}:s=44100:d={dur}",
                    "-filter:a", f"volume={vol}",
                    "-c:a","aac",path], capture_output=True)
    return path if os.path.exists(path) and os.path.getsize(path) > 100 else None

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
                  font_size, color, position, script, bg_style, bg_vol, video_length):
    out = "/tmp/final.mp4"
    W,H = (1080,1920) if "9:16" in aspect else (1920,1080)
    
    max_dur = 30.0
    if "1 minute" in video_length: max_dur = 60.0
    elif "3 minutes" in video_length: max_dur = 180.0
    elif "5 minutes" in video_length: max_dur = 300.0
    
    dur = min(get_duration(voice_path), max_dur)
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
        chunk_size = 1
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
               "[1:a]volume=1.2[v];[2:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first[a]",
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
                "-filter_complex","[1:a]volume=1.2[v];[2:a]volume=1.0[b];[v][b]amix=inputs=2:duration=first[a]",
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
# WELCOME SCREEN (STEP 3 PREMIUM LAYOUT CUSTOMIZATION)
# ══════════════════════════════════════
if "welcome_done" not in st.session_state:
    st.session_state.welcome_done = False

if not st.session_state.welcome_done:
    user_name = cfg.get("user_name","Creator")
    st.markdown("""
<style>
@keyframes fadeIn { from { opacity: 0; transform: translateY(15px); } to { opacity: 1; transform: translateY(0); } }
.stApp{background:#060913!important}
.main .block-container{padding:0!important;max-width:100%!important}
#MainMenu,footer,header{visibility:hidden!important}

/* Premium Enter Button */
.stButton>button{
    background: linear-gradient(135deg, #7c3aed, #2563eb) !important;
    color: white !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 14px 40px !important;
    font-size: 15px !important;
    font-weight: 700 !important;
    letter-spacing: 3px !important;
    text-transform: uppercase !important;
    box-shadow: 0 8px 24px rgba(124, 58, 237, 0.4) !important;
    transition: all 0.3s ease !important;
    width: 100% !important;
}
.stButton>button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 12px 30px rgba(124, 58, 237, 0.6) !important;
    opacity: 0.95 !important;
}
</style>""",unsafe_allow_html=True)

    st.markdown(f"""
<link href='https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;900&family=Orbitron:wght@800&display=swap' rel='stylesheet'>
<div style='min-height:85vh; background:#060913; display:flex; flex-direction:column;
     align-items:center; justify-content:center; text-align:center; padding:50px 20px; font-family:Montserrat,sans-serif;'>
    
    <div style='background: rgba(255, 255, 255, 0.03); 
                backdrop-filter: blur(12px); 
                -webkit-backdrop-filter: blur(12px);
                border: 1px solid rgba(255, 255, 255, 0.07); 
                border-radius: 24px; 
                padding: 50px 60px; 
                max-width: 650px; 
                width: 100%;
                box-shadow: 0 20px 50px rgba(0,0,0,0.3);
                animation: fadeIn 0.8s ease-out; '>
        
        <div style='letter-spacing:10px; font-size:14px; font-weight:400; color:#a78bfa; margin-bottom:8px;'>
            WELCOME TO
        </div>
        
        <div style='letter-spacing:4px; font-size:48px; font-weight:900; 
             background: linear-gradient(90deg, #a78bfa, #60a5fa);
             -webkit-background-clip: text; -webkit-text-fill-color: transparent;
             font-family: Orbitron, sans-serif; margin-bottom:20px;
             filter: drop-shadow(0 2px 10px rgba(124,58,237,0.3));'>
            BRAINREEL
        </div>

        <div style='width:80px; height:2px; background: linear-gradient(90deg, #7c3aed, #2563eb); margin:0 auto 24px;'></div>

        <div style='font-size:12px; color:#9ca3af; letter-spacing:4px; text-transform:uppercase; margin-bottom:35px; font-weight:500;'>
            Make Your Life Fast With AI
        </div>

        <div style='font-size:22px; color:#f3f4f6; margin-bottom:10px; font-weight:400;'>
            Welcome back, <span style="color:#60a5fa; font-weight:600;">{user_name}</span> 👋
        </div>
        
        <div style='font-size:14px; color:#9ca3af; margin-bottom:30px; letter-spacing:0.5px;'>
            🎬 AI-Powered Faceless Video Engine
        </div>
        
        <div style='font-size:11px; color:rgba(255,255,255,0.25); letter-spacing:2px; text-transform:uppercase; margin-bottom:10px;'>
            OpenRouter &nbsp;•&nbsp; Pexels &nbsp;•&nbsp; Edge-TTS &nbsp;•&nbsp; FFmpeg
        </div>
    </div>
</div>
<div style='text-align:center; font-size:10px; color:#374151; letter-spacing:2px; text-transform:uppercase; padding-bottom:20px; font-family:Montserrat;'>
    Revamped &amp; Engineered — Ahsan Raza
</div>
""",unsafe_allow_html=True)

    c1,c2,c3 = st.columns([1,1.2,1])
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
.watermark{font-size:9px;color:#2a2a3a;letter-spacing:2px;
    text-transform:uppercase;text-align:center;
    padding:10px 0 4px;border-top:1px solid #1a1a2e;}

/* Navigation option font update */
div[data-testid="stRadio"] div[role="radiogroup"] label [data-testid="stMarkdownContainer"] p {
    font-size: 19px !important;
    font-weight: 700 !important;
    color: #f0f0f0 !important;
    letter-spacing: 0.5px !important;
    padding: 4px 0 !important;
}
</style>
""",unsafe_allow_html=True)

# ══════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════
with st.sidebar:
    st.markdown("""
    <div class="brand-logo">
        <div class="brand-title">🎬 BrainReel</div>
        <div class="brand-sub">AI Faceless Video Generator</div>
    </div>""",unsafe_allow_html=True)
    st.markdown("---")
    st.markdown('<div class="section-header">Navigation</div>',unsafe_allow_html=True)
    page = st.radio(label="",
                    options=["🎬  Generate Video","⚙️  Settings"],
                    label_visibility="collapsed")
    st.markdown("---")
    st.markdown('<div class="section-header">Status</div>',unsafe_allow_html=True)
    api_set = bool(cfg.get("openai_api_key") or cfg.get("openrouter_api_key")
                   or os.environ.get("OPENROUTER_API_KEY"))
    st.markdown(
        f'<span class="badge {"badge-ready" if api_set else "badge-warn"}">'
        f'{"✓ API Ready" if api_set else "⚠ API Not Set"}</span>',
        unsafe_allow_html=True)
    st.markdown("<br><br>",unsafe_allow_html=True)
    st.caption("v3.0 · BrainReel Edition")
    st.markdown(
        '<div class="watermark">Revamped &amp; Engineered — Ahsan Raza</div>',
        unsafe_allow_html=True)

# ══════════════════════════════════════
# GENERATE VIDEO PAGE
# ══════════════════════════════════════
if page == "🎬  Generate Video":
    st.markdown("## 🎬 Generate Video")
    st.caption("Fill in the details and let AI do the magic!")

    tab1, tab2, tab3 = st.tabs(
        ["📝  Script", "🎨  Style", "🔊  Voice & Music"])

    # ── TAB 1: Script ──
    with tab1:
        st.markdown('<div class="card-title">📝 Video Script</div>',
                    unsafe_allow_html=True)
        video_subject = st.text_input("Video Topic / Subject",
            placeholder="e.g. 5 mind-blowing facts about space")
        script_mode = st.radio("Script Mode",
            ["🤖 AI Auto Generate","✍️ Write Manually"], horizontal=True)
        if script_mode == "✍️ Write Manually":
            manual_script = st.text_area("Your Script",
                placeholder="Sirf narration text — koi [brackets] nahi...",
                height=180)
        else:
            manual_script = ""
        col1, col2 = st.columns(2)
        with col1:
            video_language = st.selectbox("Language",
                ["English","Urdu","Hindi","Arabic","Chinese"])
        with col2:
            video_length = st.selectbox("Video Length",
                ["30 seconds","1 minute","3 minutes","5 minutes"])

    # ── TAB 2: Style ──
    with tab2:
        st.markdown('<div class="card-title">🎨 Visual Style</div>',
                    unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        with col1:
            video_aspect = st.selectbox("Aspect Ratio",
                ["9:16 (Vertical / TikTok)","16:9 (Horizontal / YouTube)"])
        with col2:
            st.selectbox("Video Source",["Pexels (Free)"])
        st.markdown("**Subtitle Settings**")
        col3, col4 = st.columns(2)
        with col3:
            font_size = st.slider("Font Size", 20, 80, 42)
        with col4:
            subtitle_position = st.selectbox("Position",
                ["Bottom","Center","Top"])
        subtitle_color = st.color_picker("Subtitle Color","#FFFFFF")

    # ── TAB 3: Voice & Music + GENERATE ──
    with tab3:
        st.markdown('<div class="card-title">🔊 Voice & Music</div>',
                    unsafe_allow_html=True)

        voice_display = st.selectbox("TTS Voice", list(VOICE_MAP.keys()))
        selected_voice = VOICE_MAP[voice_display]

        col_a, col_b = st.columns(2)
        with col_a:
            voice_speed = st.slider("🏃 Voice Speed", 1, 100, 50, format="%d%%",
                help="1%=Slowest | 50%=Normal | 100%=Fastest")
        with col_b:
            voice_deep = st.slider("🎵 Voice Deepness", 1, 100, 50, format="%d%%",
                help="1%=High Pitch | 50%=Normal | 100%=Deep Voice")

        col_p, col_e = st.columns([1, 2])
        with col_p:
            if st.button("🔊 Preview Voice"):
                with st.spinner("🎙️ Preview ban raha hai..."):
                    try:
                        prev_text = PREVIEW_TEXTS.get(
                            selected_voice, "Hello! This is a preview.")
                        ab = run_preview(selected_voice, prev_text,
                                         voice_speed, voice_deep)
                        st.audio(ab, format="audio/mp3")
                        st.success("✅ Preview ready!")
                    except Exception as e:
                        st.error(f"❌ {e}")

        st.markdown("---")

        bg_music = st.selectbox("🎵 Background Music",
            ["No Music","Calm","Upbeat","Cinematic","Random"])
        bg_volume = st.slider("🔉 BG Volume", 0, 100, 30,
            disabled=(bg_music == "No Music"))

        st.markdown("---")

        eta = ETA_MAP.get(video_length, "~3 min")
        st.info(f"⏱️ Estimated generation time: **{eta}** for {video_length}")

        if st.session_state.get("gen_step", 0) > 0:
            if st.button("🔄 Reset — Naya Video"):
                for k in ["gen_step","gen_script","gen_voice",
                          "gen_vtt","gen_clips","gen_output"]:
                    st.session_state.pop(k, None)
                st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 2, 1])
        with c2:
            gen_btn = st.button("🚀 Generate Video", use_container_width=True)

        if gen_btn:
            if not video_subject and not manual_script:
                st.error("⚠️ Topic ya script enter karo pehle!")
            else:
                pexels_key = (cfg.get("pexels_api_key") or
                              os.environ.get("PEXELS_API_KEY",""))
                or_key = (cfg.get("openrouter_api_key") or
                          os.environ.get("OPENROUTER_API_KEY",""))
                if not or_key:
                    st.error("❌ OpenRouter key Settings mein daalo!")
                elif not pexels_key:
                    st.error("❌ Pexels key Settings mein daalo!")
                else:
                    defs = {"gen_step":0,"gen_script":"","gen_voice":"",
                            "gen_vtt":None,"gen_clips":[],"gen_output":""}
                    for k,v in defs.items():
                        if k not in st.session_state:
                            st.session_state[k] = v

                    try:
                        prog = st.progress(0)
                        stat = st.empty()

                        if st.session_state["gen_step"] < 1:
                            stat.info("📝 Step 1/4 — Script generate ho rahi hai...")
                            if manual_script:
                                st.session_state["gen_script"] = clean_script(manual_script)
                            else:
                                st.session_state["gen_script"] = generate_script_api(
                                    video_subject, video_length, video_language, cfg)
                            st.session_state["gen_step"] = 1
                        prog.progress(25)
                        stat.success(
                            f"✅ Step 1 — Script ready! "
                            f"({len(st.session_state['gen_script'].split())} words)")

                        if st.session_state["gen_step"] < 2:
                            stat.info("🎙️ Step 2/4 — Voice generate ho rahi hai...")
                            vp, vtt = generate_voice(
                                st.session_state["gen_script"],
                                selected_voice, voice_speed, voice_deep)
                            st.session_state["gen_voice"] = vp
                            st.session_state["gen_vtt"] = vtt
                            st.session_state["gen_step"] = 2
                        prog.progress(50)
                        stat.success("✅ Step 2 — Voice + Subtitles ready!")

                        if st.session_state["gen_step"] < 3:
                            stat.info("🖼️ Step 3/4 — Video clips fetch ho rahe hain...")
                            kw = video_subject or \
                                " ".join(st.session_state["gen_script"].split()[:3])
                            urls = fetch_pexels(kw, 6, cfg)
                            if not urls:
                                st.warning("⚠️ Pexels clips nahi mile — topic change karo!")
                                st.stop()
                            clips = [download_clip(u, i)
                                     for i, u in enumerate(urls[:6])]
                            st.session_state["gen_clips"] = clips
                            st.session_state["gen_step"] = 3
                        prog.progress(75)
                        stat.success(
                            f"✅ Step 3 — "
                            f"{len(st.session_state['gen_clips'])} clips ready!")

                        if st.session_state["gen_step"] < 4:
                            stat.info(
                                "🎬 Step 4/4 — Video compose ho rahi hai... "
                                "⏳ Page band mat karo!")
                            out = compose_video(
                                st.session_state["gen_clips"],
                                st.session_state["gen_voice"],
                                st.session_state["gen_vtt"],
                                video_aspect, font_size,
                                subtitle_color, subtitle_position,
                                st.session_state["gen_script"],
                                bg_music, bg_volume,
                                video_length)
                            st.session_state["gen_output"] = out
                            st.session_state["gen_step"] = 4
                        prog.progress(100)
                        
                        final_dur = get_duration(st.session_state["gen_output"])
                        stat.success(
                            f"🎉 Video ban gayi! Length: {final_dur:.1f}s")

                        with st.expander("📝 Generated Script dekho"):
                            st.write(st.session_state["gen_script"])

                        if os.path.exists(st.session_state["gen_output"]):
                            with open(st.session_state["gen_output"],"rb") as f:
                                vbytes = f.read()
                            st.video(vbytes)
                            st.download_button(
                                "⬇️ Video Download Karo",
                                data=vbytes,
                                file_name=f"brainreel_{video_subject[:20]}.mp4",
                                mime="video/mp4",
                                use_container_width=True)

                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
                        st.warning(
                            "💡 Connecting aaya tha? "
                            "Dobara Generate dabao — wahan se continue hoga!")

# ══════════════════════════════════════
# SETTINGS PAGE
# ══════════════════════════════════════
elif page == "⚙️  Settings":
    st.markdown("## ⚙️ Settings")
    st.caption("API keys aur models configure karo.")
    s1, s2 = st.tabs(["🔑 API Keys","🤖 Models"])

    with s1:
        st.markdown('<div class="card-title">🔑 API Keys</div>',
                    unsafe_allow_html=True)
        for label, key, ph in [
            ("OpenAI API Key","openai_api_key","sk-..."),
            ("OpenRouter API Key","openrouter_api_key","sk-or-..."),
            ("Pexels API Key","pexels_api_key","Pexels key"),
            ("Pixabay API Key","pixabay_api_key","Pixabay key"),
        ]:
            val = st.text_input(label, value=cfg.get(key,""),
                                type="password", placeholder=ph, key=f"inp_{key}")
            st.markdown(
                f'<span class="key-status {"key-set" if cfg.get(key) else "key-empty"}">'
                f'{"✓ Set hai" if cfg.get(key) else "○ Empty"}</span>',
                unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save API Keys"):
            for _, key, __ in [
                ("","openai_api_key",""),
                ("","openrouter_api_key",""),
                ("","pexels_api_key",""),
                ("","pixabay_api_key",""),
            ]:
                cfg[key] = st.session_state.get(f"inp_{key}","")
            if save_config(cfg):
                st.success("✅ Keys save ho gayi!")
                st.rerun()
            else:
                st.error("❌ Save nahi hua!")

    with s2:
        st.markdown('<div class="card-title">🤖 Model Settings</div>',
                    unsafe_allow_html=True)
        providers = ["OpenAI","OpenRouter","DeepSeek",
                     "Moonshot","Google Gemini","Ollama"]
        curr = cfg.get("llm_provider","OpenAI")
        pidx = providers.index(curr) if curr in providers else 0
        llm_provider = st.selectbox("LLM Provider", providers, index=pidx)

        opts = MODEL_LISTS.get(llm_provider, ["Custom (type below)"])
        saved = cfg.get("model_name","")
        didx = opts.index(saved) if saved in opts else len(opts)-1
        sel = st.selectbox("Model (List se chuno)", opts, index=didx)

        if sel == "Custom (type below)":
            model_name = st.text_input("Ya khud likho",
                value=saved if saved not in opts else "",
                placeholder="koi bhi model")
        else:
            model_name = sel

        base_url = st.text_input("Base URL (optional)",
            value=cfg.get("base_url",""),
            placeholder="Default ke liye khali chhodo")

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("💾 Save Model Settings"):
            cfg.update({"llm_provider":llm_provider,
                        "model_name":model_name,"base_url":base_url})
            if save_config(cfg):
                st.success("✅ Saved!")
                st.rerun()
            else:
                st.error("❌ Save nahi hua!")
