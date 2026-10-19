---
name: video
description: Produz um vídeo narrado sobre qualquer assunto (Shorts/Reels/TikTok ou YouTube horizontal), do tema ao arquivo final, com o MoneyPrinterOmni e um time de produção (pesquisa, auditoria, crítica, arte, clipes, edição, render, thumbnail, publicação e direção) — pesquisa com fonte, roteiro criticado, narração na duração alvo, imagens reais (vídeos da web, stock, imagens, gráficos ou gravações do usuário) sincronizadas frase a frase e render. Use quando pedirem para criar, roteirizar ou montar um vídeo.
---

# video — do tema ao vídeo final

Entrada: `<tema> [duração em s, padrão 60] [formato 9:16|16:9|1:1] [idioma, padrão pt-BR]`,
vinda do pedido do usuário.

Funciona com qualquer assistente de IA que tenha terminal, busca na web e consiga ver imagens
(para conferir quadros e prévias). Sem visão, peça ao usuário para conferir as prévias.

Você orquestra. Cada etapa tem um papel em `.agents/roles/` (`pesquisador`, `critico`,
`sugestor-de-pauta`, `montador-mpt`, `cacador-de-clipes`, `editor-de-clipes`):
- se a sua ferramenta tem subagentes, delegue cada papel a um, usando o arquivo do papel como
  instrução e passando a pasta do projeto e a etapa;
- se não tem, execute os papéis você mesmo, em sequência, lendo o arquivo de cada um antes.

Regras gerais em `.agents/setup.md`; perfil de cada canal em `.agents/canais/`; gostos do criador
em `.agents/gostos.md`; regras por assunto em `.agents/nichos/`.
Contratos de arquivo em `.agents/pipeline.md`; receitas em `.agents/playbooks/` (`yt-dlp.md`,
`ffmpeg-timeline.md`, `moneyprinter.md`).

## 0. Setup, canal e brief

Leia `.agents/setup.md` (regras e prioridades) e descubra o canal do vídeo (regras em "Canais"
no setup). Leia a ficha `.agents/canais/<canal>.md`, os gostos `.agents/gostos.md` e a ficha do
nicho `.agents/nichos/<nicho>.md`.

Crie `storage/projects/<slug>/` (slug curto, kebab-case) e `brief.md` com: `canal:`, tema,
ângulo/tese e só o que muda em relação à ficha (público, tom, duração, formato, idioma, voz).
Pergunte ao usuário só o que mudar o vídeo e não der para inferir (ex.: ângulo de um tema amplo).

Ritmo de narração para estimar o roteiro: ≈ 2,5 palavras/s (≈ 150 por minuto) em pt-BR, en e es
com `--voice-rate 1.0–1.05`; ajuste pelo teste de áudio.

## Etapas

1. `pesquisador` → `research.md`, `sources.json` (material visual por cena), `script.txt`,
   `music-plan.md`. Todo fato com fonte; temas das últimas semanas pedem busca mais profunda.
2. Em paralelo: `critico` (conteúdo), `sugestor-de-pauta` e `auditor` (passe de fatos).
3. Se o critico disser `REVISAR`, o auditor `CORRIGIR` ou houver sugestão de alto ganho,
   `pesquisador` revisa. Repita 2–3 no máximo 2 vezes.
4. `diretor-de-arte` → `arte.md` e `arte.json` (legenda, textos na tela, ritmo, ideias de thumbnail).
5. `diretor` (modo aprovação) → `aprovacao-NN.md`. **Pare e mostre ao usuário** esse pacote
   (roteiro, duração, clima da música e plano visual de cada bloco, arte, pendências). Só continue
   com o aval dele.
6. `montador-mpt` (modo tempo): `--stop-at audio` até bater a duração (texto primeiro; velocidade
   só ±10%), depois `--stop-at subtitle` e `scripts/srt_to_timing.py` → `timing.json`.
   Em seguida (modo trilha): `music.json` a partir do `music-plan.md` e `scripts/build_music.py`
   → `bgm.mp3`, várias músicas trocando nas viradas da história.
7. `cacador-de-clipes` → `shotlist.json`, com os textos na tela do `arte.md` nos campos `text`.
   Cada cena começa no início de uma frase; `dur` vai até o início da próxima; a soma deve ser
   ≥ áudio. Se faltar material, pergunte ao usuário se ele grava/envia algo ou aceita stock.
7b. `animador` → para cada item do `shotlist.json` com `anim`, renderiza `raw/anim_NN.mp4`
   (Remotion, em `animations/`) com a `dur` exata e o formato do brief, usando as cores do `arte.json`.
8. `editor-de-clipes` → `scripts/build_timeline.py <projeto> --aspect <formato> --preview`,
   confere a prévia (olhando a imagem) e escreve `credits.md`.
9. `montador-mpt` (modo render) → `output/final.mp4` com `--video-source local`,
   `--video-concat-mode sequential`, `--video-transition-mode none`, `--video-clip-duration` ≥ maior
   clipe, `--bgm-type custom --bgm-file <slug>.mp3` e a legenda do `arte.json`.
10. Em paralelo: `critico` (passe visual) e `auditor` (passe de direitos). Se `REVISAR`/`CORRIGIR`,
    refaça só as cenas apontadas (`build_timeline.py --only 07,12`) e renderize de novo — no
    máximo 2 rodadas.
11. Em paralelo: `designer-de-thumbnail` (`scripts/build_thumbnail.py` → `publicacao/thumb-*.png`)
    e `redator-de-publicacao` (`publicacao/publicacao.md`: títulos, descrição, créditos, tags).
12. `diretor` (modo entrega) → `entrega.md`: `PRONTO` ou `REFAZER <etapa>`. Anote o vídeo no
    "Histórico" da ficha do canal.
13. Relatório final: caminho do vídeo, thumbnails, títulos e descrição prontos para colar,
    pendências e fontes. Nada é publicado.

## Onde achar imagem, por tipo de assunto

Resumo geral; a ficha do nicho tem o detalhe e os cuidados de cada assunto.

| Assunto | Primeira opção | Alternativas |
|---|---|---|
| Jogos, apps, produtos, tecnologia | vídeo do criador/marca, demos, reviews (YouTube, X, TikTok) | gravação de tela do usuário, prints |
| Notícias e acontecimentos | vídeo da própria notícia, coletivas, canais oficiais | prints de manchetes (`image`), stock |
| História, ciência, espaço, natureza | Wikimedia Commons, NASA/ESA, archive.org (domínio público) | documentários (trechos curtos), stock |
| Dinheiro, economia, dados, saúde | gráfico gerado com os números do `research.md` (`image`) | stock de contexto |
| Pessoas e lugares | vídeo oficial/entrevista; stock para lugares | fotos de Commons |
| Ideias abstratas, transições | stock Pexels/Pixabay | ilustração gerada, texto em tela |
| Tutorial, passo a passo | gravação de tela do usuário | prints anotados |

Stock pelo próprio MPT: `cli.py --video-script "..." --video-terms "termo,termo" --stop-at materials`
baixa para `storage/cache_videos/` (termos em inglês funcionam melhor). Confira o conteúdo antes de usar.

## Scripts

Rode com `python3` da raiz do repo (só biblioteca padrão; chamam `ffmpeg`, e `yt-dlp` via Nix).

- `scripts/srt_to_timing.py <subtitle.srt> <timing.json>` — tempos das frases da narração.
- `scripts/build_timeline.py <projeto> [--aspect 9:16|16:9|1:1] [--only 03,07] [--preview]` —
  baixa só os trechos necessários (qualquer site do yt-dlp) e gera cada clipe sem áudio, na duração
  exata. `kind`: `fill` (preenche cortando; `x`/`y` posicionam), `window` (gravação de janela),
  `fit` (conteúdo inteiro sobre fundo desfocado; `zoom` 0–1 amplia o centro), `image` (zoom lento);
  `text`/`text_pos` desenham o texto na tela de cada cena com o estilo do `arte.json`.
  Detalhes no docstring.
- `scripts/build_thumbnail.py <projeto> --from <clipe> --at <s> --text "LINHA 1|LINHA 2" [--size]
  [--out] [--preview]` — capa 1280x720 ou 1080x1920 com o estilo do `arte.json`.
- `scripts/arte.py` — leitura do `arte.json` e texto com ffmpeg, usado pelos outros scripts.
- `scripts/build_music.py <projeto> [--duration s] [--preview]` — junta as faixas do `music.json`
  com crossfade, volume normalizado e loop de faixas curtas; copia para `storage/bgm/<slug>.mp3`.

## O que já aprendemos

- O Python do projeto só roda dentro de `nix develop --command ...` (`libstdc++` vem do flake).
- Em `sequential`, `combine_videos` usa só os primeiros `--video-clip-duration` segundos de cada
  arquivo, na ordem dada — por isso os clipes saem já cortados na duração da cena.
- Horários de contact sheet (`fps`+`tile`) podem estar deslocados: confirme com seek exato e confira
  de novo no arquivo em 1080p.
- Interface/documento 16:9 em vídeo vertical: `fit` com `zoom` ≈ 0.6 deixa legível; cortar com
  `fill` perde o que importa.
- Legenda branca some em fundo claro: use fundo de legenda.
- Trechos de terceiros curtos (≤ 8 s), sem áudio e creditados; prefira o autor original.
- Uma música só no vídeo inteiro cansa: troque de clima nas viradas (≥ 3 climas em 60 s).
  Faixas de clima diferente têm volumes muito diferentes; o `build_music.py` normaliza.

## Regras

Não pule a parada do passo 5. Não publique nem envie o vídeo para lugar nenhum. Reporte falhas de
etapa com o erro real. Apague de `storage/tasks/` as tasks de teste descartadas.
