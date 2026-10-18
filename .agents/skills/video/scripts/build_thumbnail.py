"""Monta uma thumbnail a partir de um quadro do vídeo (ou de uma imagem) com texto curto.

Uso:
  python3 build_thumbnail.py <projeto> --from timeline/07.mp4 --at 1.5 --text "A IA COPIOU|A ADOBE" \\
      [--size 1280x720|1080x1920] [--out publicacao/thumb-A.png] [--preview]
  python3 build_thumbnail.py <projeto> --image raw/foto.png --text "..."

Tire o quadro de timeline/ ou raw/: o output/final.mp4 tem a legenda queimada.
"|" separa as linhas: a primeira sai na cor "color" e as seguintes na cor "accent" do bloco
"thumbnail" do arte.json (padrões em arte.py). O tamanho da fonte se ajusta à linha mais longa.
--preview junta todas as publicacao/thumb-*.png num mosaico (publicacao/thumbs_preview.png).
"""

import argparse
import glob
import os
import subprocess

import arte


def build(project: str, args: argparse.Namespace) -> str:
    w, h = (int(v) for v in args.size.split("x"))
    style = arte.load(project)["thumbnail"]
    lines = [line.strip() for line in args.text.split("|") if line.strip()]
    longest = max(len(line) for line in lines)
    # largura média de um caractere em fonte bold ≈ 0,64 do tamanho (com folga)
    size = int(min(h * (0.17 if w > h else 0.085), w * 0.88 / (longest * 0.64)))
    gap = int(size * 1.08)
    top = h * (0.92 if w > h else 0.72) - gap * len(lines)

    src = args.image or args.source

    def resolve(path: str) -> str:
        return path if os.path.isabs(path) else os.path.join(project, path)

    seek = [] if args.image else ["-ss", str(args.at)]
    chain = [
        f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
        "eq=contrast=1.12:saturation=1.3:brightness=-0.04",
        "vignette=PI/4.5",
        f"drawbox=x=0:y={int(top - gap * 0.4)}:w={w}:h={h}:color=black@0.35:t=fill",
    ]
    out = resolve(args.out)
    for i, line in enumerate(lines):
        chain.append(arte.drawtext(
            line, os.path.join(project, "raw", f"_thumb_{os.path.basename(out)}_{i}.txt"),
            font=style["font"], color=style["color"] if i == 0 else style["accent"], size=size,
            x="(w-text_w)/2", y=str(int(top + gap * i)), border=max(4, size // 14),
        ))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", *seek, "-i", resolve(src), "-frames:v", "1",
         "-vf", ",".join(chain), out],
        check=True,
    )
    return out


def preview(project: str) -> str | None:
    thumbs = sorted(glob.glob(os.path.join(project, "publicacao", "thumb-*.png")))
    if not thumbs:
        return None
    out = os.path.join(project, "publicacao", "thumbs_preview.png")
    inputs = [arg for t in thumbs for arg in ("-i", t)]
    scaled = "".join(f"[{i}]scale=-2:360[t{i}];" for i in range(len(thumbs)))
    stack = "".join(f"[t{i}]" for i in range(len(thumbs)))
    graph = scaled + (f"{stack}hstack=inputs={len(thumbs)}" if len(thumbs) > 1 else "[t0]null")
    subprocess.run(["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", graph, out], check=True)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("project")
    origin = parser.add_mutually_exclusive_group(required=True)
    origin.add_argument("--from", dest="source", help="vídeo de onde tirar o quadro")
    origin.add_argument("--image", help="imagem de fundo")
    parser.add_argument("--at", type=float, default=0.0, help="segundo do quadro (com --from)")
    parser.add_argument("--text", required=True, help='linhas separadas por "|"')
    parser.add_argument("--size", default="1280x720", help="1280x720 (YouTube) ou 1080x1920 (Shorts)")
    parser.add_argument("--out", default="publicacao/thumb-A.png")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()

    project = os.path.abspath(args.project)
    print("thumbnail:", build(project, args))
    if args.preview:
        print("preview:", preview(project))


if __name__ == "__main__":
    main()
