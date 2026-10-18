"""Monta a trilha de fundo com várias músicas a partir do music.json do projeto.

Uso: python3 build_music.py <pasta do projeto> [--duration 59.5] [--preview]

music.json:
{
  "crossfade": 1.5,
  "cues": [
    {"start": 0,    "mood": "alegre",  "url": "https://.../faixa.mp3", "ss": 0,
     "title": "Faixa", "author": "Autor", "license": "CC BY 4.0", "gain_db": 0},
    {"start": 34.3, "mood": "sombrio", "file": "raw/music/outra.mp3", "ss": 12}
  ]
}
"start" é o segundo do vídeo em que a música entra (início de uma frase do timing.json); cada
música toca até o "start" da próxima, com crossfade. "ss" é o ponto da faixa onde começar;
faixas curtas entram em loop. Todas são normalizadas para o mesmo volume percebido.

Gera <projeto>/bgm.mp3 e uma cópia em storage/bgm/<slug>.mp3 (pasta que o MoneyPrinterTurbo
aceita em --bgm-file). Imprime o valor para usar com --bgm-type custom --bgm-file.
--preview gera <projeto>/raw/bgm_preview.mp3 com a narração por cima, se existir <projeto>/audio.mp3.
"""

import argparse
import json
import os
import shutil
import subprocess
import urllib.parse
import urllib.request

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))


def _local(project: str, cue: dict) -> str:
    if "file" in cue:
        path = cue["file"]
        return path if os.path.isabs(path) else os.path.join(project, path)
    url = cue["url"]
    name = os.path.basename(urllib.parse.unquote(urllib.parse.urlparse(url).path)) or "faixa.mp3"
    out = os.path.join(project, "raw", "music", name)
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=120) as response, open(out, "wb") as f:
            shutil.copyfileobj(response, f)
    return out


def _duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout)


def _video_duration(project: str) -> float:
    timeline = os.path.join(project, "timeline")
    if os.path.isdir(timeline):
        clips = sorted(f for f in os.listdir(timeline) if f.endswith(".mp4"))
        if clips:
            return sum(_duration(os.path.join(timeline, c)) for c in clips)
    with open(os.path.join(project, "timing.json"), encoding="utf-8") as f:
        return json.load(f)[-1]["end"] + 1.0


def build(project: str, duration: float) -> str:
    with open(os.path.join(project, "music.json"), encoding="utf-8") as f:
        plan = json.load(f)
    xf = float(plan.get("crossfade", 1.5))
    cues = sorted(plan["cues"], key=lambda c: float(c["start"]))

    inputs, chains = [], []
    for i, cue in enumerate(cues):
        start = float(cue["start"])
        end = float(cues[i + 1]["start"]) if i + 1 < len(cues) else duration
        seg_start = max(0.0, start - xf / 2)
        seg_end = min(duration, end + xf / 2) if i + 1 < len(cues) else duration
        length = seg_end - seg_start
        inputs += ["-stream_loop", "-1", "-ss", str(cue.get("ss", 0)), "-t", f"{length:.3f}",
                   "-i", _local(project, cue)]
        fade_in = xf if i else 0.3
        fade_out = xf if i + 1 < len(cues) else min(2.5, length / 3)
        delay = round(seg_start * 1000)
        chains.append(
            f"[{i}]aformat=channel_layouts=stereo,loudnorm=I=-18:TP=-2:LRA=11,aresample=44100,"
            f"volume={float(cue.get('gain_db', 0))}dB,"
            f"afade=t=in:st=0:d={fade_in},afade=t=out:st={length - fade_out:.3f}:d={fade_out},"
            f"adelay={delay}|{delay}[a{i}]"
        )
    mix = "".join(f"[a{i}]" for i in range(len(cues)))
    graph = ";".join(chains) + f";{mix}amix=inputs={len(cues)}:normalize=0:duration=longest[out]"
    out = os.path.join(project, "bgm.mp3")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, "-map", "[out]",
         "-t", f"{duration:.3f}", "-c:a", "libmp3lame", "-b:a", "192k", out],
        check=True,
    )
    for i, cue in enumerate(cues):
        print(f"{float(cue['start']):6.1f}s  {cue.get('mood', '?'):<12} {cue.get('title', cue.get('url', cue.get('file')))}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--duration", type=float, help="duração total (padrão: soma da timeline)")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    project = os.path.abspath(args.project)
    duration = args.duration or _video_duration(project)
    out = build(project, duration)

    slug = os.path.basename(project.rstrip("/"))
    bgm_dir = os.path.join(REPO, "storage", "bgm")
    os.makedirs(bgm_dir, exist_ok=True)
    shutil.copyfile(out, os.path.join(bgm_dir, f"{slug}.mp3"))
    print(f"trilha: {out} ({duration:.1f}s)")
    print(f"render: --bgm-type custom --bgm-file {slug}.mp3")

    voice = os.path.join(project, "audio.mp3")
    if args.preview and os.path.exists(voice):
        preview = os.path.join(project, "raw", "bgm_preview.mp3")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", voice, "-i", out, "-filter_complex",
             "[1]volume=0.2[m];[0][m]amix=inputs=2:normalize=0:duration=longest", preview],
            check=True,
        )
        print(f"prévia com narração: {preview}")


if __name__ == "__main__":
    main()
