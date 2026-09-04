# Diretório de testes do MoneyPrinterTurbo

Este diretório contém testes unitários do projeto **MoneyPrinterTurbo**.

## Estrutura de diretórios

- `services/`: testes unitários e de controladores organizados por domínio
  - `test_task.py`: testes do pipeline de tarefas
  - `test_task_manager.py`: testes das filas em memória e Redis
  - `test_controller_*.py`: testes dos controladores da API separados por domínio
  - `test_video.py`, `test_voice.py`: testes dos serviços de mídia
- `test_main.py`: teste do ponto de entrada da aplicação

## Executando os testes

A suíte de CI usa pytest, que também executa os testes existentes baseados em `unittest.TestCase`:

```bash
# Executar todos os testes
uv run python -X utf8 -m pytest -q test

# Executar um arquivo de teste específico
uv run python -X utf8 -m pytest -q test/services/test_video.py

# Executar uma classe de teste específica
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService

# Executar um método de teste específico
uv run python -X utf8 -m pytest -q test/services/test_video.py::TestVideoService::test_preprocess_video
```

Para executar a mesma verificação de cobertura por branch usada na CI:

```bash
uv run python -X utf8 -m coverage run -m pytest -q test
uv run python -m coverage report
```

Os testes de provedores reais são ignorados por padrão. Para executar testes que podem chamar serviços externos de TTS ou LLM, defina `MPT_RUN_INTEGRATION_TESTS=1` e forneça as credenciais necessárias dos provedores.

## Adicionando novos testes

Ao adicionar testes para outros componentes, siga estas diretrizes:

1. Nomeie os arquivos como `test_<dominio>.py` e mantenha cada arquivo focado em um único domínio.
2. Divida suítes amplas de controladores em arquivos como `test_controller_video.py`.
3. Use funções pytest ou `unittest.TestCase`; o pytest coleta ambos.
4. Nomeie funções e métodos de teste com o prefixo `test_`.

## Recursos de teste

Coloque os arquivos necessários aos testes no diretório `test/resources`.
