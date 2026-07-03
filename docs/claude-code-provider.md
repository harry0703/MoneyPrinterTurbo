# Claude Code as the LLM engine (local, no API key)

MoneyPrinterTurbo can generate scripts, search terms and social metadata using a
**locally installed Claude Code CLI** instead of a cloud LLM API. It reuses your
existing Claude login, so generation consumes your **Claude subscription** rather
than per-token API billing.

Set in `config.toml`:

```toml
llm_provider = "claude_code"
# Optional overrides (all can be left empty):
claude_code_path = ""            # absolute path to the `claude` binary; empty = auto-detect on PATH
claude_code_model_name = ""      # e.g. "claude-opus-4-8", "opus", "sonnet"; empty = CLI default
claude_code_timeout = 180        # max seconds per generation
claude_code_extra_args = []      # advanced: extra CLI flags, e.g. ["--fallback-model", "sonnet"]
```

No `api_key` / `base_url` is needed — those fields are ignored for this provider.

## Native (no Docker)

1. Install Claude Code — https://docs.claude.com/en/docs/claude-code
2. Log in once so credentials are stored under `~/.claude`:
   ```bash
   claude   # follow the login prompt, then exit
   ```
3. Set `llm_provider = "claude_code"` and run the app as usual.

The app shells out to `claude -p "<prompt>" --output-format text` in a temporary
working directory (so it never reads this repo's files), and uses the response as
the generated text.

## Docker (Windows or Linux)

The `claude` CLI is baked into the image (Node.js + `@anthropic-ai/claude-code`),
so you only need to provide credentials by mounting the host `~/.claude` directory.

1. Copy the env template and point it at your host Claude directory:
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   - Linux / macOS: `CLAUDE_HOST_DIR=/home/youruser/.claude`
   - Windows: `CLAUDE_HOST_DIR=C:\Users\youruser\.claude`

2. Set `llm_provider = "claude_code"` in `config.toml`.

3. Start it:
   ```bash
   docker compose up --build
   ```
   - WebUI: http://127.0.0.1:8501
   - API:   http://127.0.0.1:8080/docs

### If the container isn't authenticated

Some hosts store the OAuth token in the OS keychain/credential manager rather than
in a file, so mounting `~/.claude` may not carry the token. In that case (or if you
prefer not to mount the host folder — leave `CLAUDE_HOST_DIR` empty to use the local
`./.claude-config` fallback), authenticate once inside the container:

```bash
docker compose run --rm api claude setup-token
```

The token is written into the mounted directory and reused by both the `webui` and
`api` services on every run.

> Note: `docker-compose.release.yml` pulls a prebuilt image that does **not** include
> the Claude Code CLI. Use `docker compose up --build` (which builds from the local
> `Dockerfile`) when using the `claude_code` provider.
