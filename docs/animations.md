# Animações (Remotion)

`animations/` é um projeto [Remotion](https://www.remotion.dev) (React + TypeScript) para gráficos, plantas técnicas e ilustrações animadas renderizadas em mp4. Fica isolado do código Python.

## Instalação reproduzível

```sh
nix develop                       # node 24 + chromium + ffmpeg
npm ci --prefix animations        # usa animations/package-lock.json (versões exatas)
```

Sem Nix: Node conforme `animations/.nvmrc`. Todos os pacotes `remotion` e `@remotion/*` devem ter a mesma versão exata. Para atualizar, use `npm run upgrade --prefix animations`. No `nix develop`, `PUPPETEER_EXECUTABLE_PATH` aponta para o Chromium do Nix. Fora dele, o Remotion baixa o Chrome Headless Shell no primeiro render.

## Uso

```sh
cd animations
npm run studio                                   # preview no navegador
npx remotion render HelloChart out/hello.mp4     # 1080x1920, 30 fps
npx remotion render HelloChartWide out/hello.mp4 # 1920x1080
npx remotion render HelloChart out/hello.mp4 --props='{"title":"Vendas","values":[10,40,25]}'
npm run typecheck
```

Composições ficam em `animations/src/` e são registradas em `Root.tsx`.

## Composições (9:16, 1080x1920, 30 fps)

Todas aceitam `title`, `note` (nota de rodapé, ex.: "Ilustração…") e `durationSeconds`, que define a duração exata do mp4 (`calculateMetadata` em `lib.tsx`); a animação se ajusta ao tempo total. Cores e fonte estão em `lib.tsx`; a faixa inferior fica livre para a legenda.

| Id | O que mostra | Props principais |
|---|---|---|
| `ReverseFlow` | fluxo em etapas numeradas com um ponto percorrendo o trilho | `steps: string[]` |
| `AgentSwarm` | grade de funções preenchida por N agentes até X% | `agents`, `percent`, `caption` |
| `ByteCompare` | funções original × recriada, byte a byte; `retry` falha na 1ª tentativa e passa na 2ª (em `retryAt`); último byte em cinza = ignorado | `functions`, `different`, `retry`, `retryAt`, `ignored`, `original`, `recreated`, `result` |
| `TimelineAnos` | barras "anos × semanas" e pares programa → alternativa | `before`, `after`, `ratio`, `apps: {from,to}[]` |

```sh
npx remotion render ReverseFlow ../storage/projects/<slug>/raw/anim_01.mp4 --props='{"durationSeconds":7.4,"steps":["A","B","C"]}'
npx remotion still ByteCompare out/preview.png --frame=240   # conferir um quadro
```

Nas cenas do `shotlist.json` use `"anim": "<Id>"`, `"file": "raw/anim_NN.mp4"`, `"kind": "fill"` (ver `.agents/pipeline.md`). A saída em `animations/out/` é ignorada pelo git.

Licença: o Remotion é gratuito para indivíduos e equipes pequenas; empresas maiores precisam de licença paga (veja remotion.dev/license).
