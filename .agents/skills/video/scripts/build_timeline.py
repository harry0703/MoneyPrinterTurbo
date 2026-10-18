"""Gera timeline/NN.mp4 (sem áudio, duração exata) a partir do shotlist.json.

Uso: python3 build_timeline.py <pasta do projeto> [--aspect 9:16|16:9|1:1] [--only 03,07] [--preview]

Cada item do shotlist precisa de "n", "dur" e "kind", mais uma origem:
  - "file": caminho local (relativo à pasta do projeto ou absoluto) e "ss" (início no arquivo), ou
  - "url" (YouTube, TikTok, X, Vimeo, archive.org…; ou "source": "youtube:<id>") e "start":
    baixa só o trecho em 1080p para raw/.

kind:
  fill    preenche o quadro cortando o que sobra (filmagem, gameplay, stock). "x"/"y" (0–1)
          posicionam o corte; padrão centro.
  window  igual a fill, mas tira a barra de título de uma gravação de janela ("top", padrão 0.05).
  fit     mostra o conteúdo inteiro sobre ele mesmo desfocado (tela de programa, slide, gráfico,
          documento, vídeo de orientação diferente). "zoom" (0–1) mantém só a faixa central da
          largura; "crop" aceita um filtro crop do ffmpeg no lugar.
  image   imagem estática (foto, print, gráfico gerado) com zoom lento.
Aliases antigos: game/vert → fill, gta → window, app → fit com zoom 0.62.

--preview monta raw/timeline_preview.png com um quadro de cada clipe para conferir visualmente.
"""

import argparse
import json
import os
import subprocess
import sys

MARGIN = 1.0  # segundos baixados a mais antes do início, para o corte cair em quadro bom
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}
ALIASES = {"game": ("fill", {}), "vert": ("fill", {}), "gta": ("window", {}), "app": ("fit", {"zoom": 0.62})}


def _fill(w: int, h: int, item: dict, top: float = 0.0) -> str:
    pre = f"crop=iw:ih*{1 - top}:0:ih*{top}," if top else ""
    x, y = float(item.get("x", 0.5)), float(item.get("y", 0.5))
    return (
        f"{pre}scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}:max(0\\,min(iw-{w}\\,iw*{x}-{w / 2})):max(0\\,min(ih-{h}\\,ih*{y}-{h / 2})),"
        "setsar=1,fps=30"
    )


def _fit(w: int, h: int, item: dict) -> str:
    crop = item.get("crop")
    if not crop and "zoom" in item:
        z = float(item["zoom"])
        crop = f"crop=iw*{z}:ih*0.8:iw*{(1 - z) / 2}:ih*0.08"  # corta também legendas queimadas
    fg = f"[0]{crop + ',' if crop else ''}scale={w}:{h}:force_original_aspect_ratio=decrease,setsar=1[fg]"
    bg = (
        f"[0]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
        "boxblur=30:5,eq=brightness=-0.2[bg]"
    )
    lift = round(h * 0.09) if h > w else 0  # no vertical, sobe para não colidir com a legenda
    return f"{fg};{bg};[bg][fg]overlay=(W-w)/2:(H-h)/2-{lift},setsar=1,fps=30"


def _filter(w: int, h: int, item: dict) -> list[str]:
    kind = item["kind"]
    if kind == "fill":
        return ["-vf", _fill(w, h, item)]
    if kind == "window":
        return ["-vf", _fill(w, h, item, top=float(item.get("top", 0.05)))]
    if kind == "fit":
        return ["-filter_complex", _fit(w, h, item)]
    if kind == "image":
        frames = round(float(item["dur"]) * 30)
        return [
            "-vf",
            f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2},"
            f"zoompan=z='min(zoom+0.0008,1.15)':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
            f"d={frames}:s={w}x{h}:fps=30,setsar=1",
        ]
    sys.exit(f"cena {item['n']}: kind desconhecido {kind!r}")


def _source(project: str, item: dict) -> tuple[str, float]:
    if "file" in item:
        path = item["file"]
        return (path if os.path.isabs(path) else os.path.join(project, path)), float(item.get("ss", 0))

    url = item.get("url")
    source = item.get("source", "")
    if not url and source.startswith("youtube:"):
        url = "https://www.youtube.com/watch?v=" + source.split(":", 1)[1]
    if not url:
        sys.exit(f"cena {item['n']}: sem 'file', 'url' nem 'source'")

    start = float(item["start"])
    begin = max(0.0, start - MARGIN)
    end = start + float(item["dur"]) + MARGIN
    vid = "".join(c if c.isalnum() or c in "-_" else "_" for c in (source or url)[-40:])
    out = os.path.join(project, "raw", f"hi_{vid}_{begin:g}.mp4")
    if not os.path.exists(out):
        os.makedirs(os.path.dirname(out), exist_ok=True)
        subprocess.run(
            ["nix", "shell", "nixpkgs#yt-dlp", "nixpkgs#ffmpeg", "-c", "yt-dlp", "-q", "--no-warnings",
             "-f", "bv*[height<=1080][ext=mp4]/bv*[height<=1080]/b[height<=1080]/b", "--remux-video", "mp4",
             "--download-sections", f"*{begin:g}-{end:g}", "--force-keyframes-at-cuts",
             "-o", out, url],
            check=True,
        )
    return out, start - begin


def build(project: str, item: dict, size: tuple[int, int]) -> str:
    kind, defaults = ALIASES.get(item["kind"], (item["kind"], {}))
    item = {**defaults, **item, "kind": kind}
    src, ss = _source(project, item)
    out = os.path.join(project, "timeline", f"{item['n']}.mp4")
    loop = ["-loop", "1"] if kind == "image" else []
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *loop, "-ss", f"{ss:g}", "-i", src, "-t", str(item["dur"]), "-an",
         *_filter(*size, item), "-c:v", "libx264", "-crf", "20", "-preset", "fast", "-pix_fmt", "yuv420p", out],
        check=True,
    )
    return out


def _duration(path: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout)


def preview(project: str, clips: list[str], size: tuple[int, int]) -> str:
    tw = 144 if size[1] > size[0] else 256
    th = round(tw * size[1] / size[0])
    tiles = []
    for i, clip in enumerate(clips):
        tile = os.path.join(project, "raw", f"_tile{i}.png")
        label = os.path.splitext(os.path.basename(clip))[0]
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", str(min(0.6, _duration(clip) / 2)), "-i", clip,
             "-frames:v", "1", "-vf",
             f"scale={tw}:{th},drawtext=text='{label}':x=4:y=4:fontsize=18:fontcolor=yellow:box=1", tile],
            check=True,
        )
        tiles.append(tile)
    cols = min(10 if tw == 144 else 6, len(tiles))
    rows = -(-len(tiles) // cols)
    pad = cols * rows - len(tiles)
    inputs = [arg for t in tiles for arg in ("-i", t)]
    inputs += ["-f", "lavfi", "-i", f"color=black:s={tw}x{th}:d=1"] * pad
    labels = "".join(f"[{j}]" for j in range(cols * rows))
    out = os.path.join(project, "raw", "timeline_preview.png")
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex",
         f"{labels}xstack=inputs={cols * rows}:grid={cols}x{rows}", "-frames:v", "1", out],
        check=True,
    )
    for tile in tiles:
        os.remove(tile)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    parser.add_argument("--aspect", choices=sorted(SIZES), default="9:16")
    parser.add_argument("--only", help="números de cena separados por vírgula")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    project = os.path.abspath(args.project)
    size = SIZES[args.aspect]
    with open(os.path.join(project, "shotlist.json"), encoding="utf-8") as f:
        shots = json.load(f)
    for item in shots:
        item["n"] = f"{int(item['n']):02d}"
    only = {f"{int(n):02d}" for n in args.only.split(",")} if args.only else None

    os.makedirs(os.path.join(project, "timeline"), exist_ok=True)
    for item in shots:
        if only and item["n"] not in only:
            continue
        build(project, item, size)

    clips = [os.path.join(project, "timeline", f"{item['n']}.mp4") for item in shots]
    total = 0.0
    for clip in clips:
        dur = _duration(clip)
        total += dur
        print(f"{os.path.basename(clip)} {dur:.2f}s")
    print(f"total {total:.2f}s")
    if args.preview:
        print("preview:", preview(project, clips, size))


if __name__ == "__main__":
    main()
