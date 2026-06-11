# Guia de despacho: instalar e rodar o MoneyPrinterTurbo no PC do usuário

> **Atalho para Windows:** o repositório inclui o instalador **DEMO** em
> [`instaladores/`](../../../instaladores/README.md) (autoria THM TECNOLOGIA),
> com instalação completa em fluxo único. Os instaladores da versão BR
> Completa (todos os provedores de IA, iPhone local e remoto) são distribuídos
> pela THM TECNOLOGIA mediante contato (Telegram: t.me/rdllmsu) — se o
> usuário for o proprietário, ele já os possui.

> **Para a conversa/agente que for executar este guia:** sua missão é deixar o
> MoneyPrinterTurbo rodando de forma **prática e visual** no computador do
> usuário — ou seja, a **WebUI aberta no navegador** em
> `http://127.0.0.1:8501`, gerando um vídeo de teste com sucesso. Execute as
> etapas na ordem, verifique cada uma antes de seguir, e use a seção de
> solução de problemas quando algo falhar. O usuário fala português; conduza
> tudo em português e prefira a opção mais simples que funcionar.

## O que será instalado

MoneyPrinterTurbo gera vídeos curtos completos (9:16, 16:9, 1:1) a partir de
um assunto digitado: LLM escreve o roteiro → TTS narra → legendas sincronizadas
→ baixa footage de stock → monta e composita o MP4 final. A interface visual é
uma WebUI Streamlit com suporte a português (`webui/i18n/pt.json`).

Requisitos de máquina: ~2 GB de disco para dependências + espaço para os
vídeos; qualquer CPU moderna serve (GPU NVIDIA é opcional, só acelera).

## Etapa 0 — Decidir o modo de instalação

Pergunte/detecte e escolha **um** caminho:

| Modo | Quando usar | Pré-requisitos |
|---|---|---|
| **A. Docker** (mais simples) | Docker Desktop já instalado ou o usuário aceita instalá-lo | Docker + Docker Compose |
| **B. Python nativo** (mais leve) | Sem Docker; controle total | Python 3.11 ou 3.12 (**não** 3.13+). FFmpeg e ImageMagick são **opcionais**: o app usa o FFmpeg embutido do pacote `imageio-ffmpeg` como fallback (`utils.get_ffmpeg_binary()`), e o MoviePy 2.x renderiza legendas via Pillow, sem ImageMagick |

Detecção rápida:

```bash
docker --version          # existe? → considere modo A
python3 --version         # 3.11.x ou 3.12.x? → modo B ok
ffmpeg -version           # necessário no modo B
```

## Etapa 1 — Obter o código

```bash
git clone https://github.com/ThalesAndrades/MoneyPrinterTurbo.git
cd MoneyPrinterTurbo
```

(Sem git: baixar o ZIP do repositório no GitHub e extrair.)

## Etapa 2 — Obter as chaves (5 minutos, gratuitas)

O usuário precisa de **duas chaves** para a pilha de custo zero:

1. **Pexels** (footage de stock, gratuita): criar conta em
   https://www.pexels.com/api/ e copiar a API key.
2. **LLM** — escolher um:
   - Qualquer chave OpenAI-compatível que o usuário já tenha
     (OpenAI, DeepSeek, Groq, Gemini etc.);
   - **Ollama local** (sem chave): `ollama pull llama3.1` se já instalado;
   - **Pollinations** (gratuito, sem chave obrigatória): `llm_provider = "pollinations"`.

A narração (edge-tts) e as legendas (provider `edge`) são gratuitas e não
precisam de chave. Voz em português: `pt-BR-FranciscaNeural-Female` ou
`pt-BR-AntonioNeural-Male`.

## Etapa 3 — Configurar

```bash
cp config.example.toml config.toml
```

Editar `config.toml` — mínimo necessário:

```toml
[app]
video_source = "pexels"
pexels_api_keys = ["CHAVE_PEXELS_AQUI"]
llm_provider = "openai"            # ou pollinations / ollama / deepseek...
openai_api_key = "CHAVE_LLM_AQUI"  # use o par de chaves do provider escolhido
openai_model_name = "gpt-4o-mini"
subtitle_provider = "edge"
voice_name = "pt-BR-FranciscaNeural-Female"
```

Referência completa de todas as opções: [configuration.md](configuration.md).
Presets prontos (custo zero / totalmente local / produção):
[examples.md](examples.md) §4.

## Etapa 4A — Subir com Docker

```bash
docker compose up
```

- WebUI sobe em `http://127.0.0.1:8501`.
- O compose já monta `config.toml` e `storage/`; a imagem já corrige a
  policy do ImageMagick e o `PYTHONPATH`.
- GPU NVIDIA: `docker compose -f docker-compose.gpu.yml up`.

Pule para a Etapa 5.

## Etapa 4B — Subir com Python nativo

**Dependências de sistema primeiro:**

| SO | Comandos |
|---|---|
| Windows | Instalar Python 3.11/3.12 de python.org (marcar "Add to PATH"); FFmpeg: `winget install ffmpeg` (ou baixar e pôr no PATH); ImageMagick: `winget install ImageMagick.ImageMagick` |
| macOS | `brew install python@3.12 ffmpeg imagemagick` |
| Linux (Debian/Ubuntu) | `sudo apt install python3.11 python3.11-venv ffmpeg imagemagick` |

**Dependências Python** (prefira `uv`, que usa o `uv.lock` travado):

```bash
pip install uv          # se uv não existir
uv sync --frozen        # cria .venv com versões exatas
# alternativa sem uv:  python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
```

**Iniciar a interface visual:**

```bash
./webui.sh        # macOS/Linux
webui.bat         # Windows (duplo clique funciona)
```

Os launchers detectam sozinhos `.venv`/uv/streamlit, exportam `PYTHONPATH` e,
se a porta 8501 estiver ocupada, escolhem automaticamente outra entre
8502–8599 (a URL certa aparece no terminal: `***** WebUI address: ... *****`).

> Linux: se a renderização de legenda falhar com erro de ImageMagick/policy,
> edite `/etc/ImageMagick-6/policy.xml` e remova a linha
> `<policy domain="path" rights="none" pattern="@*"/>` (é o mesmo patch que o
> Dockerfile aplica).

## Etapa 5 — Verificação (o teste visual)

1. Abrir `http://127.0.0.1:8501` no navegador (ou a porta indicada no terminal).
2. Trocar o idioma da interface para **Português** no seletor do topo.
3. Preencher só o campo de assunto: por exemplo, *"5 curiosidades sobre o oceano"*.
4. Conferir: formato **9:16**, voz `pt-BR-FranciscaNeural-Female`, legendas
   ativadas, e clicar em **Gerar vídeo**.
5. Acompanhar o log na tela; ao terminar, o preview do vídeo aparece na
   própria página e o arquivo fica em `storage/tasks/<task_id>/final-1.mp4`.

✅ **Critério de sucesso do despacho:** o vídeo de teste reproduz no preview
com narração em português, legendas sincronizadas e música de fundo.

Smoke test barato antes do vídeo completo (1 chamada de LLM, sem encode):

```bash
python cli.py --video-subject "teste" --stop-at script
```

## Etapa 6 (opcional) — Ligar a API para automação

```bash
python main.py    # FastAPI em http://127.0.0.1:8080, docs em /docs
```

Exemplos prontos de `curl` com polling e download: [examples.md](examples.md) §2.

## Solução de problemas do despacho

| Sintoma | Causa / ação |
|---|---|
| `ModuleNotFoundError: app` | `PYTHONPATH` sem a raiz do projeto — use os launchers `webui.sh`/`webui.bat`, que já exportam |
| Python 3.13 instalado | Incompatível (`requires-python >=3.11,<3.13`) — instalar 3.12 ao lado e criar o venv com ele |
| FFmpeg não encontrado | Instalar e garantir no PATH, ou apontar `IMAGEIO_FFMPEG_EXE` para o binário |
| Erro de ImageMagick ao renderizar legenda | Aplicar o patch da policy (ver Etapa 4B) ou usar Docker |
| Porta 8501 ocupada / WinError 10013 | O launcher troca de porta sozinho (8502–8599); no Windows, checar portas reservadas: `netsh interface ipv4 show excludedportrange protocol=tcp` |
| Travado em "generating script" | Chave/modelo/base_url do LLM errados — testar com `--stop-at script` e ler o log |
| TTS falha ou trava | Rede instável com edge-tts; aumentar `edge_tts_timeout` no config ou trocar a voz |
| "No materials found" | Quota/chave do Pexels, ou termos muito específicos — adicionar mais chaves (rotação automática) ou trocar `video_source` |
| Encode falha no final | Deixar `video_codec = "libx264"` (o fallback automático já tenta isso) |
| Ollama inacessível de dentro do Docker | A detecção de container reescreve para `host.docker.internal` sozinha; se falhar, usar esse host manualmente no `ollama_base_url` |

Tabela completa de depuração: [recipes.md](recipes.md) §Debug.

## Mapa de conhecimento para a conversa de despacho

Esta skill (`.claude/skills/moneyprinterturbo-expert/`) acompanha o repositório.
Numa sessão do Claude Code aberta na pasta do projeto, ela é carregada
automaticamente. Ordem de leitura recomendada para o agente:

1. **SKILL.md** — modelo mental do pipeline e convenções;
2. **este guia** — instalação e validação visual;
3. **examples.md** — comandos prontos para o que o usuário pedir depois;
4. **configuration.md / recipes.md / pipeline.md / api-and-webui.md /
   patterns.md** — referência profunda sob demanda.
