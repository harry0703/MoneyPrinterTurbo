# AGENTS.md

Instruções gerais do repositório: veja `CLAUDE.md`.

## Time de produção de vídeo

O fluxo multiagente para produzir vídeos (pesquisa → roteiro → crítica → clipes → edição →
render) está em `.agents/pipeline.md`, com receitas em `.agents/playbooks/`:

- `yt-dlp.md` — buscar, baixar em baixa resolução, "assistir" com contact sheets, baixar trechos
- `ffmpeg-timeline.md` — clipes sem áudio no formato do vídeo, com duração exata por cena, e gráficos
- `moneyprinter.md` — teste de duração, tempos das frases e render com clipes locais

Papéis (definidos para Claude Code em `.claude/agents/`; outras ferramentas podem usar os
mesmos arquivos como prompt):

| Agente | Papel |
|---|---|
| `pesquisador` | fatos com fonte, vídeos-fonte, roteiro |
| `cacador-de-clipes` | assiste os vídeos e escolhe o trecho de cada cena |
| `editor-de-clipes` | corta, enquadra e limpa os clipes com ffmpeg |
| `montador-mpt` | roda o MoneyPrinterTurbo (áudio, tempos, render) |
| `critico` | aponta falhas e buracos (conteúdo e visual), não edita |
| `sugestor-de-pauta` | propõe casos, dados, ganchos e cenas que enriquecem o vídeo |

No Claude Code, a skill `/video <tema> [duração] [formato] [idioma]` (`.claude/skills/video/`)
orquestra tudo para qualquer assunto e traz os scripts `srt_to_timing.py` e `build_timeline.py`.
