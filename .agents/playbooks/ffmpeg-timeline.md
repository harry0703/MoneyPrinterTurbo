# Playbook: clipes da timeline (sem áudio, duração exata)

O caminho normal é o script, que aplica os filtros abaixo para 9:16, 16:9 ou 1:1:

```sh
python3 .agents/skills/video/scripts/build_timeline.py storage/projects/<slug> --aspect 9:16 --preview
```

Os filtros manuais abaixo (para 1080x1920) servem para casos que o script não cobre.

Todo clipe sai com `-an`, `libx264 -crf 20 -pix_fmt yuv420p`, 30 fps e duração exata (`-t`).

## Filtros por tipo

`fill` — corte vertical central de fonte 16:9 (filmagem, gameplay, stock):
```
crop=ih*9/16:ih,scale=1080:1920,setsar=1,fps=30
```
Para mover o corte (ação fora do centro), troque o x: `crop=ih*9/16:ih:iw*0.30:0`.

`fill` com fonte já vertical ou quase:
```
scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=30
```

`fit` com `zoom` 0.62 — interface/documento ampliado sobre o próprio vídeo desfocado, subido para não colidir com a legenda:
```
[0]crop=iw*0.62:ih*0.8:iw*0.19:ih*0.08,scale=1080:-2,setsar=1[fg];
[0]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=30:5,eq=brightness=-0.2[bg];
[bg][fg]overlay=(W-w)/2:(H-h)/2-180,setsar=1,fps=30
```
O `crop` interno também tira facecam no canto e legendas queimadas na base; ajuste os
fatores se o que importa estiver fora da faixa central.

`image` — foto, print ou gráfico com zoom lento:
```
-loop 1 -i print.png ... -vf "scale=2160:-2,zoompan=z='min(zoom+0.0008,1.15)':d=<frames>:s=1080x1920:fps=30"
```

## Comando base

```sh
ffmpeg -v error -y -ss <ini> -i <fonte> -t <dur> -an <filtro> \
  -c:v libx264 -crf 20 -preset fast -pix_fmt yuv420p storage/projects/<slug>/timeline/NN.mp4
```

## Conferência

```sh
for f in timeline/*.mp4; do ffprobe -v error -show_entries format=duration:stream=width,height -of csv=p=0 "$f"; done
```
Some as durações e compare com o áudio. Gere um quadro do meio de cada clipe e olhe a imagem.

## Gráficos para temas com dados

Gráficos animados e esquemas: use o `animador` (Remotion, `docs/animations.md`). Para um gráfico
estático simples, gere um PNG com os números do `research.md` (fonte citada no rodapé do gráfico) e use `kind: image`:

```sh
nix shell nixpkgs#python3Packages.matplotlib -c python3 - <<'PY'
import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(10.8, 19.2), dpi=100)   # 9:16; use (19.2, 10.8) para 16:9
...
fig.savefig("storage/projects/<slug>/raw/grafico.png")
PY
```
(O `.venv` do projeto não tem matplotlib; o `nix shell` traz um Python com ele.)
Fonte grande (≥ 48 pt no 9:16), poucos elementos, um número de destaque por gráfico.
