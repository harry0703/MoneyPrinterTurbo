# Codex OAuth LLM Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Dockerized MoneyPrinterTurbo backend generate scripts through a host-side Codex CLI session authenticated with ChatGPT OAuth, without placing OAuth credentials inside Docker.

**Architecture:** A standard-library Python bridge runs on Windows, authenticates requests with a separate bearer token, and invokes stable non-interactive `codex exec` in an isolated read-only directory. A new MoneyPrinterTurbo `codex_oauth` provider calls that bridge through `host.docker.internal`, while existing providers continue using their current adapters.

**Tech Stack:** Python 3.11, standard-library HTTP server and subprocess APIs, `requests`, Codex CLI, Streamlit, pytest/unittest, Docker Compose.

## Global Constraints

- OAuth is mandatory for this provider; do not add an OpenAI API-key fallback.
- Never mount, copy, log, or return ChatGPT cookies, OAuth tokens, or Codex credential files.
- Do not call undocumented ChatGPT web endpoints.
- The bridge token is separate from the Codex OAuth credential and is required for generation requests.
- Codex executions use `--ephemeral`, `--sandbox read-only`, `--ask-for-approval never`, `--ignore-user-config`, `--ignore-rules`, and a dedicated empty working directory.
- Preserve all existing LLM providers and current behavior outside the new adapter.
- Do not overwrite the user's existing modifications to `app/services/video.py` or `docker-compose.yml`.
- Limit request size to 256 KiB, output to 128 KiB, timeout to 30-900 seconds, and concurrency to one Codex execution by default.

## File Map

- Create `tools/codex_oauth_bridge/codex_runner.py`: build the Codex command, execute it, parse JSONL, and classify failures.
- Create `tools/codex_oauth_bridge/server.py`: authenticated `/health` and `/v1/generate` HTTP interface with bounded input and concurrency.
- Create `tools/codex_oauth_bridge/start.ps1`: validate the standalone CLI and OAuth login, set bridge configuration, and launch the host server.
- Create `tools/codex_oauth_bridge/README.md`: host setup, login, firewall, startup, and troubleshooting instructions.
- Create `app/services/codex_bridge.py`: Docker-side bridge client with sanitized errors and timeout validation.
- Modify `app/services/llm.py`: route the new adapter and separate stable script instructions from episode input.
- Modify `app/models/llm_provider.py`: register `codex_oauth` and its provider-specific fields.
- Modify `config.example.toml`: document bridge URL, token, optional model, and timeout.
- Modify `webui/i18n/*.json`: add provider label, help text, and field labels in all nine locales.
- Modify `test/services/test_llm.py`: registry, adapter, connection, and prompt-separation coverage.
- Create `test/services/test_codex_bridge.py`: Docker-side HTTP client tests.
- Create `test/tools/test_codex_oauth_bridge.py`: host runner/server unit tests.

---

### Task 1: Codex subprocess runner

**Files:**
- Create: `tools/codex_oauth_bridge/__init__.py`
- Create: `tools/codex_oauth_bridge/codex_runner.py`
- Create: `test/tools/test_codex_oauth_bridge.py`

**Interfaces:**
- Produces: `CodexRunError(code: str, message: str)`, `build_codex_command(...) -> list[str]`, `parse_codex_jsonl(stdout: str) -> str`, and `run_codex(...) -> str`.
- Consumes: a standalone `codex` executable whose saved login is managed on the Windows host.

- [ ] **Step 1: Write failing parser and command tests**

```python
from pathlib import Path

import pytest

from tools.codex_oauth_bridge.codex_runner import (
    CodexRunError,
    build_codex_command,
    parse_codex_jsonl,
)


def test_build_command_enforces_ephemeral_read_only_execution(tmp_path: Path):
    command = build_codex_command("codex", tmp_path, "gpt-5.6-sol")
    assert command == [
        "codex", "exec", "--ephemeral", "--json",
        "--sandbox", "read-only", "--ask-for-approval", "never",
        "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check", "--model", "gpt-5.6-sol", "-",
    ]


def test_parse_jsonl_returns_last_completed_agent_message():
    stream = "\n".join([
        '{"type":"item.completed","item":{"type":"agent_message","text":"draft"}}',
        '{"type":"item.completed","item":{"type":"agent_message","text":"final narration"}}',
        '{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":3}}',
    ])
    assert parse_codex_jsonl(stream) == "final narration"


def test_parse_jsonl_rejects_failed_turn():
    with pytest.raises(CodexRunError, match="Codex execution failed") as error:
        parse_codex_jsonl('{"type":"turn.failed","error":{"message":"signed out"}}')
    assert error.value.code == "codex_failed"
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `uv run python -X utf8 -m pytest -q test/tools/test_codex_oauth_bridge.py`

Expected: FAIL because `tools.codex_oauth_bridge.codex_runner` does not exist.

- [ ] **Step 3: Implement the bounded runner**

```python
class CodexRunError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def build_codex_command(executable: str, cwd: Path, model: str = "") -> list[str]:
    command = [
        executable, "exec", "--ephemeral", "--json",
        "--sandbox", "read-only", "--ask-for-approval", "never",
        "--ignore-user-config", "--ignore-rules",
        "--skip-git-repo-check",
    ]
    if model.strip():
        command.extend(["--model", model.strip()])
    command.append("-")
    return command


def parse_codex_jsonl(stdout: str) -> str:
    final_text = ""
    for raw_line in stdout.splitlines():
        if not raw_line.strip():
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise CodexRunError("invalid_output", "Codex returned invalid JSONL output") from exc
        if event.get("type") == "turn.failed":
            raise CodexRunError("codex_failed", "Codex execution failed")
        item = event.get("item")
        if event.get("type") == "item.completed" and isinstance(item, dict):
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"].strip()
    if not final_text:
        raise CodexRunError("empty_output", "Codex returned no final narration")
    return final_text


def run_codex(instructions: str, input_text: str, model: str, timeout_seconds: int,
              executable: str = "codex") -> str:
    prompt = f"{instructions.strip()}\n\n<episode_input>\n{input_text.strip()}\n</episode_input>"
    with tempfile.TemporaryDirectory(prefix="mpt-codex-") as workdir:
        try:
            completed = subprocess.run(
                build_codex_command(executable, Path(workdir), model),
                input=prompt,
                text=True,
                encoding="utf-8",
                capture_output=True,
                cwd=workdir,
                timeout=timeout_seconds,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        except FileNotFoundError as exc:
            raise CodexRunError("codex_not_found", "Standalone Codex CLI was not found") from exc
        except subprocess.TimeoutExpired as exc:
            raise CodexRunError("timeout", "Codex execution timed out") from exc
    if completed.returncode != 0:
        raise CodexRunError("codex_failed", "Codex execution failed; verify ChatGPT sign-in")
    return parse_codex_jsonl(completed.stdout)
```

- [ ] **Step 4: Add subprocess tests and run the runner suite**

Patch `subprocess.run` to assert `cwd` is an empty temporary directory, `input` contains both XML-delimited episode input and instructions, timeout is forwarded, and stderr is not included in raised messages.

Run: `uv run python -X utf8 -m pytest -q test/tools/test_codex_oauth_bridge.py`

Expected: PASS.

- [ ] **Step 5: Commit the runner**

```powershell
git add tools/codex_oauth_bridge/__init__.py tools/codex_oauth_bridge/codex_runner.py test/tools/test_codex_oauth_bridge.py
git commit -m "feat: add isolated Codex OAuth runner"
```

### Task 2: Authenticated host HTTP bridge

**Files:**
- Create: `tools/codex_oauth_bridge/server.py`
- Modify: `test/tools/test_codex_oauth_bridge.py`

**Interfaces:**
- Consumes: `run_codex(instructions, input_text, model, timeout_seconds, executable) -> str`.
- Produces: `create_server(host, port, bridge_token, codex_executable) -> ThreadingHTTPServer` with `GET /health` and `POST /v1/generate`.

- [ ] **Step 1: Write failing HTTP tests**

```python
def test_generate_requires_bearer_token(bridge_url):
    response = requests.post(f"{bridge_url}/v1/generate", json={"instructions": "x", "input": "y"})
    assert response.status_code == 401
    assert response.json() == {"error": {"code": "unauthorized", "message": "Invalid bridge token"}}


def test_generate_returns_runner_output(bridge_url, monkeypatch):
    monkeypatch.setattr(server, "run_codex", lambda **kwargs: "narration")
    response = requests.post(
        f"{bridge_url}/v1/generate",
        headers={"Authorization": "Bearer test-token"},
        json={"instructions": "plain text", "input": "episode", "model": "", "timeout_seconds": 120},
    )
    assert response.status_code == 200
    assert response.json()["output_text"] == "narration"
```

- [ ] **Step 2: Run the focused tests and verify failure**

Run: `uv run python -X utf8 -m pytest -q test/tools/test_codex_oauth_bridge.py -k bridge_http`

Expected: FAIL because `create_server` and HTTP handlers do not exist.

- [ ] **Step 3: Implement the server**

Use `ThreadingHTTPServer`, `BaseHTTPRequestHandler`, `hmac.compare_digest`, and a `threading.BoundedSemaphore(1)`. Reject missing or invalid `Content-Length`, bodies larger than `262144`, non-JSON bodies, unknown fields, empty instructions/input, timeout values outside `30..900`, and outputs larger than `131072` UTF-8 bytes. Return only these stable error shapes:

```python
{"error": {"code": "unauthorized", "message": "Invalid bridge token"}}
{"error": {"code": "invalid_request", "message": "Request body is invalid"}}
{"error": {"code": "busy", "message": "Codex bridge is processing another request"}}
{"error": {"code": error.code, "message": str(error)}}
```

The health response is:

```python
{"status": "ok", "codex_available": shutil.which(codex_executable) is not None}
```

The module CLI accepts `--host`, `--port`, and `--codex-executable`, reads the required token only from `CODEX_BRIDGE_TOKEN`, and exits before binding when the token is absent.

- [ ] **Step 4: Test authentication, validation, concurrency, and error mapping**

Run: `uv run python -X utf8 -m pytest -q test/tools/test_codex_oauth_bridge.py`

Expected: PASS, including 401, 400, 413, 429, 502, and 504 cases.

- [ ] **Step 5: Commit the HTTP bridge**

```powershell
git add tools/codex_oauth_bridge/server.py test/tools/test_codex_oauth_bridge.py
git commit -m "feat: expose authenticated Codex host bridge"
```

### Task 3: MoneyPrinterTurbo bridge client

**Files:**
- Create: `app/services/codex_bridge.py`
- Create: `test/services/test_codex_bridge.py`

**Interfaces:**
- Produces: `CodexBridgeError`, `normalize_timeout(value) -> int`, `health(base_url, timeout_seconds=10) -> dict`, and `generate(base_url, bridge_token, instructions, input_text, model_name="", timeout_seconds=300) -> str`.
- Consumes: bridge JSON contracts from Task 2.

- [ ] **Step 1: Write failing client tests**

```python
def test_generate_sends_authenticated_bounded_request(monkeypatch):
    response = Mock(ok=True)
    response.json.return_value = {"output_text": "narration"}
    post = Mock(return_value=response)
    monkeypatch.setattr(codex_bridge.requests, "post", post)
    assert codex_bridge.generate(
        "http://host.docker.internal:9876", "secret", "rules", "episode", "", 300
    ) == "narration"
    assert post.call_args.kwargs["headers"] == {"Authorization": "Bearer secret"}
    assert post.call_args.kwargs["timeout"] == (10, 300)


def test_generate_sanitizes_remote_error(monkeypatch):
    response = Mock(ok=False, status_code=401)
    response.json.return_value = {"error": {"code": "unauthorized", "message": "Invalid bridge token"}}
    monkeypatch.setattr(codex_bridge.requests, "post", Mock(return_value=response))
    with pytest.raises(codex_bridge.CodexBridgeError, match="Invalid bridge token"):
        codex_bridge.generate("http://bridge", "secret", "rules", "episode")
```

- [ ] **Step 2: Run tests and verify import failure**

Run: `uv run python -X utf8 -m pytest -q test/services/test_codex_bridge.py`

Expected: FAIL because `app.services.codex_bridge` does not exist.

- [ ] **Step 3: Implement the HTTP client**

Use `requests.get/post`, URL normalization with `.rstrip("/")`, `(10, timeout)` connect/read timeouts, JSON type validation, and messages that never include headers, bridge tokens, full request URLs containing userinfo, or request bodies. `normalize_timeout` returns 300 for invalid values and clamps valid numbers to `30..900`.

- [ ] **Step 4: Run client tests**

Run: `uv run python -X utf8 -m pytest -q test/services/test_codex_bridge.py`

Expected: PASS for successful, unreachable, unauthorized, invalid JSON, empty output, oversized output, and timeout cases.

- [ ] **Step 5: Commit the client**

```powershell
git add app/services/codex_bridge.py test/services/test_codex_bridge.py
git commit -m "feat: add Codex bridge client"
```

### Task 4: Provider registry and LLM routing

**Files:**
- Modify: `app/models/llm_provider.py`
- Modify: `app/services/llm.py`
- Modify: `test/services/test_llm.py`

**Interfaces:**
- Consumes: `codex_bridge.generate(...) -> str`.
- Produces: provider id `codex_oauth`, adapter id `codex_bridge`, and `_generate_response(prompt: str, instructions: str = "") -> str`.

- [ ] **Step 1: Write failing provider and adapter tests**

```python
def test_codex_oauth_provider_registry_contract(self):
    provider = get_llm_provider("codex_oauth")
    self.assertEqual(provider.adapter, "codex_bridge")
    self.assertEqual(provider.default_base_url, "http://host.docker.internal:9876")
    self.assertFalse(provider.requires_api_key)
    self.assertFalse(provider.requires_model_name)
    self.assertEqual([field.config_suffix for field in provider.extra_fields], ["bridge_token", "timeout_seconds"])


def test_codex_adapter_separates_instructions_and_input(self):
    config.app.update({
        "llm_provider": "codex_oauth",
        "codex_oauth_base_url": "http://bridge:9876",
        "codex_oauth_model_name": "",
        "codex_oauth_bridge_token": "secret",
        "codex_oauth_timeout_seconds": "300",
    })
    with patch.object(llm.codex_bridge, "generate", return_value="narration") as generate:
        result = llm._generate_response("episode context", instructions="narration rules")
    self.assertEqual(result, "narration")
    generate.assert_called_once_with(
        base_url="http://bridge:9876", bridge_token="secret",
        instructions="narration rules", input_text="episode context",
        model_name="", timeout_seconds="300",
    )
```

- [ ] **Step 2: Run focused tests and verify failure**

Run: `uv run python -X utf8 -m pytest -q test/services/test_llm.py -k codex`

Expected: FAIL because the provider and adapter are not registered.

- [ ] **Step 3: Register the provider**

Add this registry entry immediately after OpenAI:

```python
LLMProviderSpec(
    "codex_oauth",
    "Codex (ChatGPT OAuth)",
    adapter="codex_bridge",
    default_base_url="http://host.docker.internal:9876",
    requires_api_key=False,
    requires_model_name=False,
    show_api_key=False,
    extra_fields=(
        LLMProviderField("bridge_token", "Codex Bridge Token", required=True, secret=True),
        LLMProviderField("timeout_seconds", "Codex Bridge Timeout", default_value="300"),
    ),
),
```

- [ ] **Step 4: Route the adapter and separate script request fields**

Change `_generate_response` to accept `instructions`. For non-Codex providers, create `effective_prompt = f"{instructions}\n\n{prompt}" if instructions else prompt` before existing provider branches. For the Codex branch, call the bridge with the two fields unchanged.

Add:

```python
def build_script_request(...parameters...) -> tuple[str, str]:
    instructions = _limit_script_text(
        custom_system_prompt, MAX_SCRIPT_SYSTEM_PROMPT_LENGTH, "custom_system_prompt"
    ) or DEFAULT_SCRIPT_SYSTEM_PROMPT
    input_text = f"""# Episode Context:
- video subject: {video_subject}
- number of paragraphs: {paragraph_number}"""
    if language:
        input_text += f"\n- language: {language}"
    if video_script_prompt:
        input_text += f"\n\n# Additional User Requirements:\n{video_script_prompt}"
    return instructions, input_text
```

Keep `build_script_prompt` as a compatibility wrapper that joins the returned values. Change `generate_script` to call `_generate_response(prompt=input_text, instructions=instructions)`. Add a regression test proving existing OpenAI-compatible providers still receive the combined prompt.

- [ ] **Step 5: Run LLM tests**

Run: `uv run python -X utf8 -m pytest -q test/services/test_llm.py`

Expected: PASS.

- [ ] **Step 6: Commit provider routing**

```powershell
git add app/models/llm_provider.py app/services/llm.py test/services/test_llm.py
git commit -m "feat: route LLM generation through Codex OAuth"
```

### Task 5: Configuration and WebUI

**Files:**
- Modify: `config.example.toml`
- Modify: `webui/i18n/de.json`
- Modify: `webui/i18n/en.json`
- Modify: `webui/i18n/es.json`
- Modify: `webui/i18n/id.json`
- Modify: `webui/i18n/pt.json`
- Modify: `webui/i18n/ru.json`
- Modify: `webui/i18n/tr.json`
- Modify: `webui/i18n/vi.json`
- Modify: `webui/i18n/zh.json`
- Modify: `test/services/test_llm.py`

**Interfaces:**
- Consumes: provider metadata from Task 4.
- Produces: selectable and testable WebUI provider configuration.

- [ ] **Step 1: Extend locale coverage tests**

Add assertions that every locale contains:

```python
required_keys = {
    "Codex Bridge Token",
    "Codex Bridge Timeout",
    "llm_provider_label.codex_oauth",
    "llm_provider_tips.codex_oauth",
}
```

Run: `uv run python -X utf8 -m pytest -q test/services/test_llm.py -k locale`

Expected: FAIL listing the missing Codex keys.

- [ ] **Step 2: Add example configuration**

```toml
# Codex CLI authenticated through ChatGPT OAuth. Start the host bridge first.
codex_oauth_base_url = ""
codex_oauth_model_name = ""
codex_oauth_bridge_token = ""
codex_oauth_timeout_seconds = "300"
```

- [ ] **Step 3: Add locale labels and help**

Use native translations for English and Chinese. For the other locales, use clear English fallback text rather than machine-invented translations. The English help text must state:

```text
##### Codex OAuth Configuration
- Sign in on the Windows host with `codex login`; no OpenAI API key is used.
- Start `tools/codex_oauth_bridge/start.ps1` before testing this provider.
- Base Url defaults to `http://host.docker.internal:9876` for Docker.
- Bridge Token must match `CODEX_BRIDGE_TOKEN` on the host and is not your OAuth token.
- Model Name is optional; leave it empty to use Codex's recommended model.
```

- [ ] **Step 4: Run registry and locale tests**

Run: `uv run python -X utf8 -m pytest -q test/services/test_llm.py`

Expected: PASS.

- [ ] **Step 5: Commit configuration and UI copy**

```powershell
git add config.example.toml webui/i18n test/services/test_llm.py
git commit -m "feat: expose Codex OAuth provider settings"
```

### Task 6: Host startup and operating documentation

**Files:**
- Create: `tools/codex_oauth_bridge/start.ps1`
- Create: `tools/codex_oauth_bridge/README.md`

**Interfaces:**
- Consumes: `python -m tools.codex_oauth_bridge.server` and standalone `codex` CLI.
- Produces: a repeatable Windows startup flow without revealing OAuth credentials.

- [ ] **Step 1: Implement the PowerShell launcher**

The script accepts `-Port 9876`, `-HostAddress 0.0.0.0`, and `-CodexExecutable codex`. It must:

```powershell
$ErrorActionPreference = 'Stop'
$command = Get-Command $CodexExecutable -ErrorAction SilentlyContinue
if (-not $command) { throw 'Standalone Codex CLI not found. Install it with: npm install -g @openai/codex' }
& $CodexExecutable login status
if ($LASTEXITCODE -ne 0) { throw 'Codex is not signed in. Run: codex login' }
if (-not $env:CODEX_BRIDGE_TOKEN) {
    throw 'Set CODEX_BRIDGE_TOKEN to a high-entropy local bridge token before starting.'
}
python -m tools.codex_oauth_bridge.server `
    --host $HostAddress --port $Port --codex-executable $command.Source
```

Do not generate or echo the token automatically because doing so encourages accidental terminal-history and log exposure.

- [ ] **Step 2: Write the operating guide**

Document standalone CLI installation, `codex login`, a PowerShell example that sets a session-only `CODEX_BRIDGE_TOKEN`, bridge startup, provider fields, `Invoke-WebRequest http://127.0.0.1:9876/health`, Docker startup order, Windows Firewall local-network restriction, and error mapping. Explicitly warn never to paste `auth.json` or browser cookies into MoneyPrinterTurbo.

- [ ] **Step 3: Verify launcher failure modes**

Run with the token unset and expect the targeted token error. Run with an invalid Codex path and expect the targeted install error. Do not print the environment or credential directories during either check.

- [ ] **Step 4: Commit startup tooling**

```powershell
git add tools/codex_oauth_bridge/start.ps1 tools/codex_oauth_bridge/README.md
git commit -m "docs: add Codex OAuth bridge startup workflow"
```

### Task 7: Full verification and local OAuth smoke test

**Files:**
- Modify only if verification reveals a defect in the files listed above.

**Interfaces:**
- Consumes: all preceding tasks.
- Produces: test evidence and a running local OAuth-backed provider.

- [ ] **Step 1: Run focused tests**

```powershell
uv run python -X utf8 -m pytest -q `
  test/tools/test_codex_oauth_bridge.py `
  test/services/test_codex_bridge.py `
  test/services/test_llm.py
```

Expected: PASS.

- [ ] **Step 2: Run the complete suite and lint changed Python files**

```powershell
uv run python -X utf8 -m pytest -q test
uv run ruff check `
  tools/codex_oauth_bridge `
  app/services/codex_bridge.py `
  app/services/llm.py `
  app/models/llm_provider.py `
  test/tools/test_codex_oauth_bridge.py `
  test/services/test_codex_bridge.py `
  test/services/test_llm.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 3: Install or expose a standalone Codex CLI and authenticate**

If `codex --version` is inaccessible because the Microsoft Store application alias denies shell execution, install the standalone CLI with `npm install -g @openai/codex`, then run `codex login` and complete the browser OAuth flow. Verify with `codex login status`. Do not inspect or copy the stored OAuth credential.

- [ ] **Step 4: Start the bridge and test from Docker**

Start the bridge with a session-only shared token. From the API container run:

```powershell
docker compose exec api python -c "import requests; print(requests.get('http://host.docker.internal:9876/health', timeout=10).json())"
```

Expected: `{'status': 'ok', 'codex_available': True}`.

- [ ] **Step 5: Generate one narration through the real bridge**

Select `Codex (ChatGPT OAuth)` in the WebUI, enter the matching bridge token, leave model empty, run the connection test, and generate a two-paragraph narration from a short episode context. Confirm the response contains narration only and that no files appear in the bridge temporary working directory after completion.

- [ ] **Step 6: Review the final diff and status**

```powershell
git diff --check
git status --short
git log --oneline -8
```

Expected: no whitespace errors; only the user's pre-existing unrelated modifications remain uncommitted.
