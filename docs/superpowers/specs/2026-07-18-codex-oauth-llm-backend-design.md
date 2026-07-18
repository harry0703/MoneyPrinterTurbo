# Codex OAuth LLM Backend Design

## Objective

Add a MoneyPrinterTurbo LLM provider that generates narration through the user's existing ChatGPT-authenticated Codex session. OpenAI Platform API keys are not used or accepted by this provider.

The provider must work when MoneyPrinterTurbo runs through the existing Docker Compose stack, preserve the current OpenAI-compatible and local providers, and avoid copying ChatGPT OAuth credentials into the repository or Docker containers.

## Constraints

- OAuth is mandatory for this provider.
- ChatGPT OAuth credentials remain on the Windows host under Codex's credential management.
- The Docker containers must not mount the Codex credential directory.
- Existing providers and their configuration remain behavior-compatible.
- The integration is local-only and is not a public multi-user service.
- Script generation must remain bounded, cancellable, and unable to edit the repository.
- The implementation must not call undocumented ChatGPT web endpoints or reuse browser cookies.

## Considered Approaches

### 1. Host bridge invoking `codex exec` (selected)

A small authenticated HTTP bridge runs on Windows and invokes the standalone Codex CLI for each request. The CLI reuses the user's persisted ChatGPT sign-in. MoneyPrinterTurbo calls the bridge through `host.docker.internal`.

Advantages:

- Uses the documented ChatGPT sign-in supported by Codex.
- Uses stable non-interactive `codex exec` rather than the experimental app-server WebSocket transport.
- Keeps OAuth credentials out of Docker.
- Provides a narrow interface tailored to text generation.

Costs:

- A host helper must be running alongside Docker.
- Each request starts a Codex execution and therefore has more latency than a direct API request.
- Codex subscription limits and availability apply.

### 2. Run Codex inside the backend container

Install a Codex runtime in the image and mount the host credential directory into the container.

Rejected because it exposes reusable ChatGPT credentials to the application container, complicates Windows-to-Linux credential storage, and broadens the impact of a container compromise.

### 3. Connect directly to Codex app-server over WebSocket

Run app-server on Windows and let the backend speak its JSON-RPC protocol.

Rejected for this version because the documented TCP WebSocket transport is experimental and unsupported. The design may migrate to app-server after that transport becomes stable.

## Architecture

### Host-side OAuth bridge

Add a Python helper under `tools/codex_oauth_bridge/` with one responsibility: accept a bounded text-generation request, run Codex, and return the final text.

Endpoints:

- `GET /health`: confirms the bridge process and Codex executable are available. It must not expose account or credential details.
- `POST /v1/generate`: accepts `instructions`, `input`, and an optional request timeout; returns `output_text` and non-sensitive execution metadata.

The bridge requires a shared bearer token supplied through the `CODEX_BRIDGE_TOKEN` host environment variable. It listens on a configurable port, defaulting to `9876`. Because Docker Desktop must reach it from a VM, the listener may bind beyond loopback, but every generation request must be authenticated. Documentation must recommend a high-entropy token and Windows Firewall scoping to local Docker networking.

The bridge runs Codex in a dedicated empty working directory with a read-only sandbox, no approvals, and no repository context. The prompt explicitly requires plain narration text and forbids tool use or file changes. The subprocess receives a fixed timeout and is terminated on timeout or client cancellation.

The bridge parses Codex's structured JSONL output and returns only the final agent message. Raw OAuth tokens, environment dumps, full prompts, and internal event streams are never logged.

### MoneyPrinterTurbo provider

Add a `codex_oauth` entry to the centralized LLM provider registry. It uses a new `codex_bridge` adapter rather than the OpenAI SDK.

Configuration keys:

- `codex_oauth_base_url`, default `http://host.docker.internal:9876`
- `codex_oauth_bridge_token`, required and preferably injected through an environment variable
- `codex_oauth_model_name`, optional; an empty value lets the authenticated Codex installation choose its recommended model
- `codex_oauth_timeout_seconds`, with a conservative bounded default

The existing WebUI provider selector exposes the bridge URL, optional model, and masked bridge token. It explains that the standalone Codex CLI must be installed, signed in with ChatGPT, and that the host bridge must be running.

### Request mapping

The current script prompt is split into two explicit bridge fields:

- `instructions`: stable narration rules and output constraints
- `input`: episode/source context, subject, language, paragraph target, and user requirements

This avoids flattening everything into one undifferentiated message. The first implementation preserves the existing UI fields. A separate follow-up can add document upload and long-form context ingestion without coupling that larger feature to OAuth support.

Other MoneyPrinterTurbo LLM tasks, such as search-term and social-metadata generation, use the same adapter but receive task-specific instructions.

## Data Flow

1. The user signs into the standalone Codex CLI through the documented ChatGPT browser flow.
2. The user starts the host bridge with a shared bearer token.
3. Docker Compose starts MoneyPrinterTurbo with the matching bridge URL and token.
4. MoneyPrinterTurbo builds the task instructions and input, then sends them to the bridge.
5. The bridge validates authentication and request limits.
6. The bridge runs a non-interactive, read-only Codex execution using the cached host OAuth session.
7. The bridge extracts the final agent text and returns it to MoneyPrinterTurbo.
8. MoneyPrinterTurbo applies its normal output validation and continues the video pipeline.

OAuth credentials never cross steps 1 or 6.

## Error Handling

The bridge returns stable error codes for:

- missing or invalid bridge token;
- Codex CLI not installed or inaccessible;
- Codex not signed in;
- subscription or usage limits;
- execution timeout or cancellation;
- empty or malformed Codex output.

MoneyPrinterTurbo maps these to sanitized provider errors and does not retry authentication or configuration failures. Transient Codex failures may use the existing bounded retry path. Neither side includes credentials, command lines containing secrets, or full episode content in error messages.

The WebUI connection test calls the bridge health endpoint and performs a minimal authenticated generation, distinguishing host reachability from Codex authentication failure.

## Security Boundaries

- No ChatGPT cookies, OAuth tokens, or Codex credential files enter Docker.
- The shared bridge token is distinct from the Codex OAuth token.
- The bridge accepts only text-generation requests; it exposes no arbitrary command, working-directory, sandbox, approval, or tool parameters.
- Codex runs outside the MoneyPrinterTurbo repository in read-only/no-approval mode.
- Request sizes, output sizes, concurrency, and execution time are bounded.
- Logs contain request identifiers, timing, status, and lengths, not prompt contents or secrets.
- The bridge is for trusted local use and must not be internet-exposed.

## Testing

### Unit tests

- Provider registry defaults and field requirements.
- Adapter request payload, bearer authentication, timeout, response parsing, and sanitized errors.
- Bridge request validation and authentication.
- Codex JSONL parsing for successful, empty, malformed, timeout, and failure streams.
- Subprocess construction enforces the dedicated working directory and read-only/no-approval settings.
- Prompt mapping keeps instructions separate from episode input.

### Integration tests

- A fake bridge validates the backend and WebUI connection-test flow in CI without OAuth.
- A manual local smoke test verifies ChatGPT browser sign-in, bridge startup, Docker-to-host connectivity, and one narration generation.
- Existing LLM provider tests must continue to pass unchanged except for registry expectations that include the new provider.

## Rollout and Operations

Provide PowerShell scripts to install/check the standalone Codex CLI, start the OAuth login flow, generate or accept a bridge token, and start the bridge. Scripts must never print stored OAuth credentials.

Document this startup order:

1. `codex login`
2. start the Codex OAuth bridge
3. `docker compose up -d`
4. select `Codex (ChatGPT OAuth)` in the WebUI and run the connection test

The existing Docker services continue to start when the bridge is absent; only requests using `codex_oauth` fail with a targeted setup message.

## Acceptance Criteria

- A user with no OpenAI API key can generate a script from the Dockerized WebUI using a ChatGPT-authenticated Codex session.
- ChatGPT OAuth credentials are not stored in the repo, Compose configuration, application config, or containers.
- The new provider can be selected and tested from the WebUI.
- Existing providers remain functional.
- Generation failures are bounded and actionable.
- Unit tests and a documented local smoke test verify the full bridge path.
