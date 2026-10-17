# Pipeline de vídeo com time de agentes

Fluxo usado pela skill `/video` (`.claude/skills/video/SKILL.md`), para qualquer assunto. Cada agente lê este arquivo
e os playbooks em `.agents/playbooks/` antes de começar.

## Pasta do projeto

Tudo de um vídeo fica em `storage/projects/<slug>/` (o `storage/` já é ignorado pelo git):

```
storage/projects/<slug>/
  brief.md          # tema, público, duração alvo, formato (9:16 padrão), idioma
  research.md       # fatos com fonte (pesquisador)
  sources.json      # vídeos candidatos (pesquisador)
  script.txt        # roteiro final, só o texto narrado
  critique/         # content-NN.md, visual-NN.md (critico), ideas-NN.md (sugestor-de-pauta)
  timing.json       # frases com início/fim, vindas da SRT (montador-mpt)
  shotlist.json     # cena -> vídeo -> trecho (cacador-de-clipes)
  raw/              # downloads (low-res para assistir, 1080p para cortar)
  timeline/NN.mp4   # clipes finais no formato do brief, sem áudio (editor-de-clipes)
  credits.md        # canal + link de cada trecho usado
  output/           # vídeo final copiado do storage/tasks/<task_id>/
```

## Etapas

| # | Agente | Entrada | Saída |
|---|---|---|---|
| 1 | `pesquisador` | brief.md | research.md, sources.json, rascunho de script.txt |
| 2 | `critico` | script.txt, research.md | critique/content-NN.md |
| 3 | `sugestor-de-pauta` | script.txt, research.md, críticas | critique/ideas-NN.md |
| 4 | `pesquisador` | críticas + sugestões | script.txt revisado (no máximo 2 rodadas de 2–4) |
| 5 | `montador-mpt` | script.txt | áudio de teste, timing.json (ajusta texto/velocidade até bater a duração) |
| 6 | `cacador-de-clipes` | timing.json, sources.json | shotlist.json, raw/ |
| 7 | `editor-de-clipes` | shotlist.json, timing.json | timeline/NN.mp4, credits.md |
| 8 | `montador-mpt` | timeline/ | output/final.mp4 |
| 9 | `critico` (passe visual) | output/final.mp4, timing.json | critique/visual-NN.md |
| 10 | volta para 6/7 se o critico reprovar o passe visual (no máximo 2 rodadas) | | |

## Contratos

`sources.json` (`type`: video | image | stock | chart | user; `license`: domínio público, CC-BY, stock, terceiro…):
```json
[{"id": "fpsq2MyWznc", "url": "https://www.youtube.com/watch?v=fpsq2MyWznc",
  "type": "video", "channel": "DryxioGTA", "license": "terceiro (trecho curto)",
  "duration": "1:40", "covers": ["bloco 2: portais entre os jogos"]}]
```

`timing.json` (um item por linha da SRT):
```json
[{"n": 1, "start": 0.098, "end": 3.598, "text": "A inteligência artificial..."}]
```

`shotlist.json` (um item por clipe; `dur` = início da próxima cena − início desta):
```json
[{"n": "01", "phrases": [1], "dur": 4.2, "url": "https://www.youtube.com/watch?v=fpsq2MyWznc",
  "start": 4.0, "kind": "fill", "why": "portais visíveis"},
 {"n": "02", "phrases": [2, 3], "dur": 3.1, "file": "raw/grafico_inflacao.png",
  "kind": "image", "why": "número citado na fala"}]
```
Origem: `url` + `start` (qualquer site do yt-dlp; baixa só o trecho) ou `file` + `ss` (local).
`kind`: `fill` (preenche o quadro cortando; `x`/`y` posicionam), `window` (gravação de janela, tira a
barra de título), `fit` (conteúdo inteiro sobre fundo desfocado; `zoom` 0–1 amplia o centro — telas,
slides, documentos, vídeo de orientação diferente), `image` (foto, print ou gráfico com zoom lento).
Quem gera os clipes é `.claude/skills/video/scripts/build_timeline.py`.

## Regras gerais

- Python do projeto só roda dentro de `nix develop --command ...` (o `.venv` usa o Python do Nix
  e precisa do `LD_LIBRARY_PATH` do flake para achar `libstdc++`).
- Fatos recentes: sempre com fonte. Nada de inventar números, datas ou nomes.
- Trechos de terceiros: curtos (≤ 8 s), sem áudio, com crédito em `credits.md`.
- A soma das durações da timeline deve ser ≥ duração do áudio.
