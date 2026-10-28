# OpenAI - Codex

Select **OpenAI - Codex** in the LLM provider settings and choose **Connect ChatGPT
with a code**. Open the OpenAI authorization page, enter the displayed code and
approve access. The UI polls for confirmation automatically. Device-code sign-in
must be enabled for the account. Use **Test LLM Connection** after connecting and
selecting a model.

This provider uses the Codex allowance of the connected ChatGPT subscription for
text and optional image generation. No API key, Codex CLI installation or shared
CLI credentials are needed. Voice and video rendering retain their existing providers.

## Image material source

Choose **OpenAI - Codex Images** under **AI Image** in Video Source. In Settings,
the AI Image Generation APIs section has a separate Responses model selector and
request timeout (`codex_image_model_name`, `codex_image_timeout`). There is no
default model. The catalog lists candidates, not account-specific image access;
the selected Responses model must support the image-generation tool for the account.
The tool chooses its image engine; do not substitute a GPT Image engine name for
the Responses model ID.

Text and images share one ChatGPT account and one device-code login. Connecting
from the image settings also connects the LLM, and an existing LLM session is
reused automatically. Disconnecting removes the shared session for both. The
LLM provider and its model remain independent of the image source and its model.

Codex produces PNG material through the existing image-to-video path, including
the existing static/zoom effects and duration handling. It does not change script,
keyword or narration generation. Each image uses the account's allowance. If a
request's result is uncertain, invalid, or cannot be saved/rendered, the job stops
without automatically generating a replacement. Only an explicit 401 permits a
single coordinated token refresh and retry. A logout or account switch invalidates
queued and in-flight image work from the previous authorization.

## Models

The selector fetches `https://models.dev/api.json` and applies the same compatibility
rules as [Jarvys](https://github.com/Hackerprod/Jarvys). The public catalog is not an
account-specific entitlement check. There is no fixed default model: choose an ID
from the list. Model IDs are preserved exactly when sending requests.

The catalog is cached locally for 24 hours. **Refresh models** bypasses the cache.
If refreshing fails, the last valid catalog remains available. Without a cache,
the UI allows entering a model ID manually. A previously selected model that is
absent from a refreshed catalog is preserved instead of silently switching models.
Catalog requests contain no ChatGPT credentials.

## Credentials and errors

Credentials are stored in `storage/auth/openai_codex.bin`, outside Git and the
configuration file. Windows uses user-scoped DPAPI encryption; other systems use
a private file. Tokens are refreshed under a lock to avoid concurrent reuse of
rotating refresh tokens. The provider never imports or changes the credentials
used by the Codex desktop app or CLI. **Disconnect ChatGPT** removes this app's
local credentials; it does not revoke other sessions.

Image work is bound to the submitting account and a persistent login revision.
Processes sharing the runtime directory coordinate credential changes and refresh
with a file lock. Disconnecting or signing in again invalidates older image work,
including a new login to the same account; normal refresh preserves the revision.
Existing credentials are migrated atomically without requiring another login.

Requests are restricted to the OpenAI authorization and Codex Responses endpoints,
without following redirects. Only completed Responses output is accepted; partial
streams and raw provider error bodies are not exposed as generated text. A 401
triggers at most one token refresh and retry. Authentication and model-picker
controls and messages use the application's existing localization system in all
14 supported languages. Extended provider setup tips follow the project's Chinese
and English convention.

The device-code and Responses protocol was inspected in Jarvys and independently
implemented in Python. See also [OpenAI authentication documentation](https://learn.chatgpt.com/docs/auth).

## Validation

Tests cover pending, cancelled and expired sign-in, encrypted Windows persistence,
concurrent token refresh, retry after 401, complete and incomplete SSE responses,
catalog filtering, cache persistence, refresh and outage recovery, and translated
Streamlit controls. Real-account sign-in was also confirmed by the user during
local testing. Automated tests use synthetic credentials.

### Reproducible live-image acceptance

Image access is separate from text access: the selected Responses model and the
connected account must be allowed to use `image_generation` on the Codex route.
A model's presence in the public catalog, a successful text request, or a plan
name alone does not establish that access. The separate **ChatGPT (Native OAuth)**
provider does not supply the Codex session used by this image source.

Sign in once through **OpenAI - Codex** in the WebUI, then run the acceptance
script from the same installation and runtime directory. If using `MPT_HOME`,
keep the same value for the WebUI and the script. Install the locked dependencies
first with `uv sync --frozen`; FFmpeg must be available through the application's
normal FFmpeg configuration.

```sh
uv run python scripts/accept_codex_image.py --model "<exact Responses model ID>" --output storage/acceptance/codex-image.json --plan pro --confirm-image-generation
```

`--model` is required and is sent unchanged. For example, to reproduce the
reported rejection for `gpt-5.6-luna`, supply that exact ID. The script does not
try other models or providers. `--plan` is optional, self-reported context; it is
not a verified entitlement and does not guarantee image access.

`--confirm-image-generation` explicitly requests one real image using the shared
account's allowance. There is no extra image generation for the static/zoom
checks: both render the received PNG. The normal transport may refresh and retry
once after an explicit HTTP 401. Other failures stop the run without regenerating.
The request timeout defaults to 300 seconds (`--timeout`), and each render plus
its decoding check is bounded to 120 seconds.

The script uses `capture_context` → `generate_images_codex` → `request_image`.
It reports success only after observing a completed response and completed image
tool result, decoding the returned PNG, and decoding frames from both rendered
two-second clips. The generated assets are written beside the JSON report.

The report contains the exact requested model, OS/Python/package/FFmpeg versions,
source revision, HTTP status and request IDs where available, response/tool IDs
and completion state, image size/hash/dimensions, and static/zoom decoding and
duration evidence. Missing server IDs remain absent or null. A failed request
produces a nonzero exit status and a sanitized report; the known HTTP 400
`tool_choice`/missing-image-tool rejection is identified without copying its raw
body. Reports never include tokens, account IDs, authorization URLs, arbitrary
prompts, image base64, or raw provider/transport exception messages.

Share the JSON report after inspection; keep credentials and generated media out
of commits. A successful report establishes that model/account combination at
that time, not availability for every account or model.

### Recorded live image acceptance

The normal image material path was tested with an existing Codex device-code
session and a self-reported Pro plan. These reports record successful generation,
response/tool IDs, decoded PNG hashes and dimensions, and decoded two-second
static/zoom renders. They contain no credentials or account identifiers:

- [gpt-5.6-luna acceptance](validation/codex-image-gpt-5.6-luna-2026-10-28.json)
- [gpt-6-luna acceptance](validation/codex-image-gpt-6-luna-2026-10-28.json)

Each report identifies the clean source commit and relevant runtime versions.
Neither response supplied a request-ID header. Success on this account does not
establish access for every account or explain a different installation's HTTP
400. The acceptance script preserves a bounded, sanitized failure classification
when an endpoint rejects the same request; it never switches models automatically.
