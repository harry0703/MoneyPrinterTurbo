# Pipeline de vídeo com time de agentes

Fluxo usado pela skill `video` (`.agents/skills/video/SKILL.md`), para qualquer assunto e qualquer
assistente de IA. Cada papel (`.agents/roles/`) lê este arquivo e os playbooks em
`.agents/playbooks/` antes de começar — seja executado por um subagente ou pela própria IA, em sequência.

## Pasta do projeto

Tudo de um vídeo fica em `storage/projects/<slug>/` (o `storage/` já é ignorado pelo git):

```
storage/projects/<slug>/
  brief.md          # canal, tema, ângulo e só o que difere da ficha do canal
  research.md       # fatos com fonte (pesquisador)
  sources.json      # vídeos candidatos (pesquisador)
  script.txt        # roteiro final, só o texto narrado
  music-plan.md     # blocos do roteiro → clima da música + faixas candidatas (pesquisador)
  music.json        # deixas de música em segundos (montador-mpt)
  bgm.mp3           # trilha montada, várias músicas com crossfade (build_music.py)
  critique/         # content-NN.md, visual-NN.md (critico), ideas-NN.md (sugestor-de-pauta)
  timing.json       # frases com início/fim, vindas da SRT (montador-mpt)
  shotlist.json     # cena -> vídeo -> trecho (cacador-de-clipes)
  raw/              # downloads (low-res para assistir, 1080p para cortar)
  timeline/NN.mp4   # clipes finais no formato do brief, sem áudio (editor-de-clipes)
  credits.md        # canal + link de cada trecho usado, e cada música com licença
  arte.md           # identidade visual do vídeo explicada (diretor-de-arte)
  arte.json         # parâmetros de legenda, texto na tela e thumbnail
  audit/            # fatos-NN.md, direitos-NN.md (auditor)
  aprovacao-NN.md   # pacote de aprovação para o usuário (diretor)
  publicacao/       # thumb-*.png, thumbs_preview.png, publicacao.md
  entrega.md        # checklist final e veredito (diretor)
  output/           # vídeo final copiado do storage/tasks/<task_id>/
```

## Etapas

| # | Papel | Entrada | Saída |
|---|---|---|---|
| 1 | `pesquisador` | brief.md | research.md, sources.json, script.txt, music-plan.md |
| 2 | `critico` · `sugestor-de-pauta` · `auditor` (fatos) | script.txt, research.md | critique/content-NN.md, critique/ideas-NN.md, audit/fatos-NN.md |
| 3 | `pesquisador` | críticas, sugestões, auditoria | script.txt revisado (no máximo 2 rodadas de 2–3) |
| 4 | `diretor-de-arte` | brief, script, music-plan, fichas | arte.md, arte.json |
| 5 | `diretor` (aprovação) | tudo acima | aprovacao-NN.md → **parada para o usuário** |
| 6 | `montador-mpt` | script.txt, music-plan.md | áudio de teste, timing.json, music.json, bgm.mp3 |
| 7 | `cacador-de-clipes` | timing.json, sources.json, arte.md | shotlist.json, raw/ |
| 7b | `animador` | shotlist.json (itens com `anim`), arte.json | raw/anim_NN.mp4 |
| 8 | `editor-de-clipes` | shotlist.json, arte.json | timeline/NN.mp4, credits.md |
| 9 | `montador-mpt` | timeline/, bgm.mp3, arte.json | output/final.mp4 |
| 10 | `critico` (visual) · `auditor` (direitos) | output/final.mp4, shotlist, music.json, credits.md | critique/visual-NN.md, audit/direitos-NN.md |
| 11 | `designer-de-thumbnail` · `redator-de-publicacao` | timeline/, arte.json, script, credits.md | publicacao/thumb-*.png, publicacao/publicacao.md |
| 12 | `diretor` (entrega) | tudo | entrega.md (`PRONTO` ou `REFAZER <etapa>`) |

Etapas com `·` rodam em paralelo. Reprovação no 10 volta para 7/8 (no máximo 2 rodadas).

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
Cena animada: `"anim": "<IdDaComposição>"` (+ `"props"` opcional), `"file": "raw/anim_NN.mp4"`,
`"kind": "fill"`; o `animador` renderiza o mp4 em `animations/` (`docs/animations.md`).
Campos opcionais `text` (texto na tela, `\n` quebra linha) e `text_pos` (`top` | `center` | `bottom`).
`kind`: `fill` (preenche o quadro cortando; `x`/`y` posicionam), `window` (gravação de janela, tira a
barra de título), `fit` (conteúdo inteiro sobre fundo desfocado; `zoom` 0–1 amplia o centro — telas,
slides, documentos, vídeo de orientação diferente), `image` (foto, print ou gráfico com zoom lento).
Quem gera os clipes é `.agents/skills/video/scripts/build_timeline.py`.

`music.json` (`start` = início, em segundos, da frase onde a música entra; ver docstring de
`build_music.py`):
```json
{"crossfade": 1.5, "cues": [
  {"start": 0, "mood": "alegre", "url": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/Monkeys%20Spinning%20Monkeys.mp3",
   "ss": 0, "title": "Monkeys Spinning Monkeys", "author": "Kevin MacLeod", "license": "CC BY 4.0"},
  {"start": 34.5, "mood": "amedrontador", "file": "raw/music/Darkest Child.mp3", "ss": 0,
   "title": "Darkest Child", "author": "Kevin MacLeod", "license": "CC BY 4.0"}]}
```

`arte.json` (seções opcionais; o que faltar usa os padrões de `scripts/arte.py`; fontes só de
`resource/fonts/`):
```json
{"legenda": {"font_name": "BeVietnamPro-Bold.ttf", "text_fore_color": "#FFFFFF",
             "stroke_color": "#000000", "stroke_width": 1.5, "position": "bottom",
             "background": true, "background_color": "#000000"},
 "texto_na_tela": {"font": "BeVietnamPro-Bold.ttf", "color": "#FFD400", "size": 96,
                   "box": true, "box_color": "#000000@0.55"},
 "thumbnail": {"font": "BeVietnamPro-Bold.ttf", "color": "#FFFFFF", "accent": "#FFD400"}}
```
O `montador-mpt` traduz `legenda` para `--font-name`, `--text-fore-color`, `--stroke-color`,
`--stroke-width`, `--subtitle-position`, `--subtitle-background-enabled` e
`--subtitle-background-color` do `cli.py`.

## Regras gerais

As regras completas e a ordem de prioridade (pedido > brief > ficha do canal > padrões) estão em
`.agents/setup.md`. Resumo:

- Python do projeto só roda dentro de `nix develop --command ...` (o `.venv` usa o Python do Nix
  e precisa do `LD_LIBRARY_PATH` do flake para achar `libstdc++`).
- Fatos recentes: sempre com fonte. Nada de inventar números, datas ou nomes.
- Trechos de terceiros: curtos (≤ 8 s), sem áudio, com crédito em `credits.md`.
- A soma das durações da timeline deve ser ≥ duração do áudio.
- Trilha variada: ≥ 3 climas em 60 s, sem repetir faixa nem clima em blocos seguidos; só música
  de licença livre, creditada em `credits.md`.
