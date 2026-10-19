# Setup — regras do time de vídeo

Regras que todo papel (`.agents/roles/`) e a skill `video` seguem em qualquer vídeo.
Leia este arquivo antes de começar qualquer etapa.

## Ordem de prioridade

1. Pedido explícito do usuário na conversa.
2. `brief.md` do vídeo (`storage/projects/<slug>/brief.md`).
3. Ficha do canal (`.agents/canais/<canal>.md`), indicada no campo `canal:` do brief.
4. Gostos do criador (`.agents/gostos.md`): música, estilo artístico, narração, linguagem.
5. Ficha do nicho (`.agents/nichos/<nicho>.md`), indicada no campo `nicho:` da ficha do canal.
6. Este setup (padrões abaixo).

Quando duas fontes conflitam, vale a de número menor. Registre no brief qualquer desvio da ficha.
Exceções que nada sobrescreve: as "Regras fixas" deste setup e os "Cuidados obrigatórios" do nicho.

## Canais

- Todo vídeo pertence a um canal. Os canais ficam em `.agents/canais/`, um arquivo por canal,
  copiado de `.agents/canais/_modelo.md`.
- Se o pedido não disser o canal: com um canal só, use-o; com vários, pergunte qual; sem nenhum,
  siga com os padrões deste setup e ofereça criar a ficha ao final.
- A ficha define identidade (nicho, público, tom), padrões de produção (voz, formato, duração,
  legenda, trilha) e os canais de referência. O brief herda tudo da ficha e só repete o que muda.
- Canais de referência servem para aprender ritmo, gancho, estrutura e edição. Nunca copie
  roteiro, bordão, vinheta, marca ou trecho de vídeo deles, a menos que a ficha diga que o
  material é liberado (ex.: canal do próprio usuário).
- Quando um vídeo terminar, anote na seção "Histórico" da ficha: data, tema, duração e o que
  funcionou ou não (o usuário pode completar com métricas depois).

## Nichos e gostos

- Cada nicho (`.agents/nichos/`) diz onde buscar informação e imagem, que trilha combina, os
  cuidados obrigatórios e o que costuma funcionar. Nicho novo: copie `_modelo.md`. Sem nicho
  definido, escolha o mais próximo e diga qual usou.
- Os gostos (`.agents/gostos.md`) guiam a escolha de música (gênero e timbre dentro do clima pedido
  pelo roteiro), o visual (estética, cores, legenda, tipo de imagem, ritmo de corte) e a narração.
  Artistas e obras citados ali são referência de clima e estética, nunca material a usar.

## Padrões (quando ficha e brief não dizem)

| Item | Padrão |
|---|---|
| Idioma | pt-BR |
| Voz | `pt-BR-AntonioNeural-Male`, `--voice-rate 1.05` |
| Formato / duração | 9:16, 60 s (≈ 150 palavras) |
| Legenda | ligada, embaixo, fundo escuro arredondado |
| Trilha | ≥ 3 climas por minuto, `--bgm-volume 0.2`, só licença livre |
| Clipes de terceiros | ≤ 8 s cada, sem áudio, com crédito |

## Regras fixas

- **Fatos:** todo número, data e nome com fonte no `research.md`; nada inventado. Assunto das
  últimas semanas pede duas fontes.
- **Imagem:** prefira o autor original a reuploads; marca d'água e facecam de terceiros saem no
  corte. Material do próprio usuário tem prioridade quando existir.
- **Música:** só licença livre (CC0, CC BY com crédito, Pixabay, faixas de `resource/songs/`).
  Nada de música comercial ou trilha de jogo/filme.
- **Créditos:** `credits.md` lista cada trecho de vídeo e cada música (título, autor, licença, link),
  pronto para colar na descrição.
- **Paradas obrigatórias:** o `diretor` leva ao usuário o pacote de aprovação (roteiro, trilha,
  plano visual e arte) antes de baixar e editar; aviso quando faltar material para uma cena.
- **Auditoria:** nada chega ao usuário com auditoria de fatos `CORRIGIR`, e nada é entregue sem
  auditoria de direitos `OK`.
- **Fechamento com o público:** todo roteiro termina convidando o espectador a **comentar as
  dúvidas** e perguntando se ele quer um **tutorial** do assunto (adapte as palavras ao tema e ao
  tom do canal; omita só o tutorial quando não fizer sentido). Vale além da "chamada final" da
  ficha do canal. Em temas de engenharia reversa, o tutorial prometido cobre código próprio,
  interoperabilidade e software aberto, nunca contornar proteções.
- **Modelo por papel:** ao delegar cada papel a um subagente, escolha o modelo pela função, não
  um só para todos. Modelo pequeno e barato (ex.: Haiku) para trabalho mecânico: operar o CLI,
  montar thumbnails, escrever a embalagem de publicação. Modelo intermediário (ex.: Sonnet) para o
  que exige julgamento, olhar visual ou código: pesquisa, auditoria, crítica, sugestão de pauta,
  direção, caça e edição de clipes, animação. Modelo mais forte só se um papel errar fatos ou
  análise repetidamente. No Claude Code, é a linha `model:` de `.claude/agents/<papel>.md`; em
  outras ferramentas, o equivalente. Ao criar um papel novo, defina o modelo na hora.
- **Embalagem honesta:** título e thumbnail só prometem o que o vídeo mostra.
- **Nunca:** publicar, enviar ou agendar o vídeo; mudar `config.toml` ou o código do app durante
  a produção; apagar arquivos fora de `storage/projects/<slug>/` e das tasks de teste que você criou.
- **Falhas:** relate o erro real com o log; não finja que uma etapa deu certo.
