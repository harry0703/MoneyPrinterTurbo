---
name: moneyprinterturbo-video
description: Use esta skill sempre que o usuário quiser criar um vídeo final a partir de um tema, título, ideia, prompt ou roteiro com o MoneyPrinterTurbo. Isso inclui vídeos curtos, com narração, educacionais, de marketing, para redes sociais e baseados em bancos de imagens e vídeos. Use-a também quando o usuário mencionar MoneyPrinterTurbo, fornecer a URL desta Skill, pedir a um agente de IA para instalar ou configurar o MoneyPrinterTurbo, precisar identificar chaves de API ausentes, corrigir uma geração com falha ou localizar e entregar um MP4 gerado. Use esta skill quando o resultado esperado for um arquivo de vídeo final, e não apenas instruções de configuração.
compatibility: Requer um agente de IA com acesso a terminal, rede, sistema de arquivos e suporte a comandos de longa duração. Compatível com macOS e Windows e utiliza exclusivamente uv.
metadata:
  author: "harry0703@hotmail.com"
  version: "1.3.2"
  upstream: "https://github.com/harry0703/MoneyPrinterTurbo"
---

# Geração de vídeo com MoneyPrinterTurbo

O usuário precisa fornecer apenas um tema ou roteiro de vídeo. Conclua automaticamente a instalação, o reaproveitamento da configuração, a geração, a espera pela conclusão e a entrega final do MP4. Não pare depois de fornecer instruções ou comandos.

## Comportamento obrigatório

1. Solicite ao usuário apenas as credenciais de API obrigatórias que estejam ausentes, tenham sido rejeitadas ou não possam ser utilizadas. Reúna todas as credenciais necessárias em uma única solicitação.
2. Não solicite confirmação antes de instalar, gerar, aguardar, usar valores padrão ou retornar o resultado.
3. Não crie nem atualize repetidamente um plano detalhado para uma solicitação padrão de geração. Envie uma única atualização curta de progresso e execute.
4. Execute o helper como um único comando em primeiro plano, com timeout de pelo menos 20 minutos.
5. Nunca faça polling com `sleep`, `echo`, `ps`, `ls` repetido ou `tail` repetido. Se o terminal retornar um ID de sessão retomável, continue aguardando na mesma sessão.
6. Não leia o log completo após uma execução bem-sucedida. Após uma falha, leia apenas o erro resumido informado ou o trecho relevante do final do log.
7. Nunca imprima chaves de API, tokens, o `config.toml` completo ou fragmentos de configuração que contenham credenciais.

## Valores padrão

A menos que o usuário solicite outra configuração, gere um vídeo vertical `9:16` em chinês, com materiais do Pexels, voz chinesa padrão do Edge TTS, legendas e música de fundo. Instale o MoneyPrinterTurbo no diretório pessoal do usuário.

## Execução

### 1. Localizar o helper

Resolva `SKILL_DIR` a partir deste arquivo `SKILL.md`. O helper é o arquivo adjacente `mpt_agent.py`. Defina o diretório de trabalho da ferramenta de terminal como `SKILL_DIR` e execute o helper pelo nome de arquivo relativo. Não coloque o caminho absoluto do helper no comando e não execute uma verificação adicional com `ls` ou `dir`.

Isso é necessário no Windows porque alguns validadores de terminal de agentes removem barras invertidas de caminhos absolutos incorporados em comandos. Usar `mpt_agent.py` com `workdir=SKILL_DIR` evita essa falha e funciona tanto no macOS quanto no Windows.

Se o cliente tiver carregado apenas o `SKILL.md` remoto, baixe o helper do repositório oficial para um diretório temporário e use esse diretório temporário como diretório de trabalho do comando:

```text
https://raw.githubusercontent.com/harry0703/MoneyPrinterTurbo/main/docs/skill/mpt_agent.py
```

### 2. Executar o helper

Não execute uma verificação separada com `uv --version`. Execute o helper diretamente. Se o shell informar explicitamente que `uv` está ausente, instale `uv` e tente o mesmo comando do helper mais uma vez.

Instalação do uv no macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Instalação do uv no Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Use este comando em primeiro plano com `workdir=SKILL_DIR` e timeout de pelo menos 20 minutos:

```bash
uv run --no-project --python 3.11 python mpt_agent.py --subject "<tema do vídeo>"
```

No Windows, não tente caminhos absolutos com barras invertidas, caminhos absolutos com barras normais nem cópias no workspace antes desse comando relativo. Se a ferramenta de terminal informar `referenced_script_path_missing`, verifique se o diretório de trabalho é exatamente `SKILL_DIR` e tente o comando relativo mais uma vez. Não fique alternando entre variantes de caminho.

Não use Docker, Conda, pip do sistema nem um ambiente virtual gerenciado manualmente.

## Tratamento dos códigos de saída

### Código de saída 0: entregar o resultado

Uma saída bem-sucedida tem este formato:

```text
MPT_RESULT
VIDEO_FILE=<caminho absoluto>/final-1.mp4
TASK_DIR=<caminho absoluto>/storage/tasks/<task_id>
LOG_FILE=<caminho absoluto>/run-<task_id>.log
RESULT_FILE=<caminho absoluto>/latest-result.json
```

`mpt_agent.py` emite `VIDEO_FILE` somente depois de confirmar que o arquivo existe e não está vazio. Não execute outro `ls`, `stat` nem comando adicional de validação do arquivo.

Se o terminal informar `exitCode=0`, mas truncar a saída ou retornar uma referência a um arquivo de histórico sem `MPT_RESULT`, não deduza que houve falha e não inspecione logs antigos. Leia este arquivo uma única vez:

```text
~/MoneyPrinterTurbo/.agent-logs/moneyprinterturbo-video/latest-result.json
```

Considere `status=completed` como sucesso. Retorne apenas o caminho absoluto do vídeo e uma descrição curta, por exemplo:

```text
O vídeo está pronto.
Tema: ...
Arquivo de vídeo: /caminho/absoluto/para/final-1.mp4
Resumo: vídeo vertical em chinês com narração, legendas e música de fundo.
```

### Código de saída 10: solicitar credenciais uma única vez

`MPT_NEEDS_INPUT` inclui apenas os campos obrigatórios, provedores de LLM recomendados e links de cadastro, requisitos personalizados compatíveis com OpenAI e links de cadastro dos provedores de materiais. Solicite apenas os valores listados e não peça credenciais já encontradas em `config.toml`.

Depois que o usuário responder, execute novamente o mesmo comando em primeiro plano usando apenas as variáveis de ambiente necessárias:

```text
MPT_LLM_PROVIDER
MPT_LLM_API_KEY
MPT_LLM_BASE_URL
MPT_LLM_MODEL_NAME
MPT_PEXELS_API_KEY
MPT_VOLCENGINE_ARK_API_KEY
MPT_OFOX_API_KEY
MPT_METASO_MINIMAX_API_KEY
```

Quando `SEEDANCE_CHARGE_CONFIRMATION_REQUIRED` estiver presente, explique que cada clipe Seedance gerado cria uma tarefa paga no Ark. Somente depois de uma confirmação explícita do usuário execute novamente com `--confirm-seedance-charge`; nunca adicione essa flag silenciosamente.

Quando `OFOX_CHARGE_CONFIRMATION_REQUIRED` estiver presente, explique que cada clipe OFox gerado cria uma tarefa paga. Somente depois de uma confirmação explícita do usuário execute novamente com `--confirm-ofox-charge`; nunca adicione essa flag silenciosamente.

Quando `METASO_MINIMAX_CHARGE_CONFIRMATION_REQUIRED` estiver presente, explique que cada clipe MiniMax H3 gerado cria uma tarefa paga na Metaso. Somente depois de uma confirmação explícita do usuário execute novamente com `--confirm-metaso-minimax-charge`; nunca adicione essa flag silenciosamente.

### Código de saída 1: corrigir ou relatar

Use `MPT_ERROR` e `LOG_FILE` para corrigir um problema recuperável e tentar novamente uma única vez. Solicite ao usuário apenas se a correção exigir uma nova chave de API. Se a nova tentativa falhar, informe a etapa que falhou, um erro resumido e o caminho do log.

Um erro de validação de caminho da ferramenta de terminal não é uma falha de geração de vídeo, porque o helper não chegou a ser iniciado. Corrija o diretório de trabalho e tente novamente o comando relativo uma única vez. Nunca peça ao usuário para copiar `mpt_agent.py`, executar comandos manualmente ou confirmar se o agente deve continuar.

## Configuração e fallback para execução em segundo plano

O helper pode ler o `config.toml` local completo para reutilizar configurações existentes, mas nunca deve imprimir seu conteúdo. Ele reutiliza automaticamente um provedor de LLM funcional e valida chaves configuradas do Pexels pelo endpoint autenticado My Collections antes da geração.

Use modo em segundo plano somente se a plataforma do agente não puder aguardar um processo em primeiro plano. Aguarde a notificação de conclusão do processo da própria plataforma sem polling e, em seguida, leia `latest-result.json` uma única vez.

## Escopo

- Ofereça suporte somente a macOS e Windows.
- Use somente uv e a CLI do MoneyPrinterTurbo.
- Não inicie Docker, WebUI nem serviços de API.
- Não execute múltiplas tarefas de vídeo simultaneamente.
- Passe requisitos adicionais do vídeo após `--`. Execute `cli.py --help` uma única vez somente quando precisar verificar uma opção desconhecida.
