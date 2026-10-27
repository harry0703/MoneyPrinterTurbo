# OpenAI - Codex: Sign in with ChatGPT

The existing `openai_codex` provider now registers MoneyPrinterTurbo through
OpenAI's official [Sign in with ChatGPT flow](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).
It uses the signed-in account's authorized ChatGPT plan access for text
generation. No API key, Codex CLI installation, or CLI credentials are required.

## Local sign-in

1. Run MoneyPrinterTurbo locally and select **OpenAI - Codex** in LLM settings.
2. Click **Continue with ChatGPT**, then **Open OpenAI authorization page**.
3. In a browser on the same computer, sign in and authorize MoneyPrinterTurbo
   to use your ChatGPT plan. OpenAI returns to a temporary `127.0.0.1` callback.
4. Return to MoneyPrinterTurbo. If sign-in did not grant plan usage, the app
   displays that state and lets you repeat authorization to enable it.
5. Choose a model returned for your account and use **Test LLM Connection**,
   or generate a script and search terms.

The callback listener belongs to the OAuth service; running the separate FastAPI
server is unnecessary. This first implementation targets browser and Python
runtime on the same computer. A browser on another machine cannot reach the
runtime's loopback callback. Docker/remote VM credential transfer is not included.

Voice, stock materials, and video-generation services remain separately configured.
The **Manage usage** link opens ChatGPT's own plan/app usage settings.

## Registration and credentials

The first sign-in uses `dynamic_agent_client` and a persistent installation host
ID. The application saves the client ID issued by OpenAI and reuses it on later
sign-ins. Every authorization uses fresh state, nonce and PKCE values. ID tokens
are signature-verified against OpenAI's JWKS and checked for issuer, audience,
expiry and nonce. Plan inference also requires the granted
`chatgpt.tokens.use.direct` scope.

Registrations remain separate even when their email addresses match. Settings
can select a saved registration or add an account. Only a fully validated
sign-in replaces the active account. Credentials live in
`storage/auth/openai_codex.bin` under the application runtime root (`MPT_HOME`
when configured). Windows uses user-scoped DPAPI; Unix files use private
permissions. Writes are atomic and refreshes are serialized across processes.
The provider does not read or modify Codex CLI/Desktop credentials.

**Disconnect ChatGPT** attempts to revoke the renewable session and clears its
local tokens, while retaining the registration and installation host ID for a
later sign-in. If revocation cannot be confirmed, the UI directs the user to
ChatGPT settings to disconnect the app there.

## Models and text generation

The model selector calls `GET https://api.openai.com/v1/models` with the active
account's OAuth access token. It displays server-listed models in server order
and sends the selected `slug` unchanged. It does not use models.dev or infer
access from a model name. An unavailable saved model remains in configuration,
but is not presented as an available option.

Text generation calls `POST https://api.openai.com/v1/responses` with the same
authorization, `store: false` and `stream: true`. Only `response.completed`
produces a successful text result. There is no fallback to an environment API
key, the ordinary OpenAI API-key provider, or ChatGPT backend-api endpoints.

## Existing connections and validation

Connections created by the old Codex device-code provider require a new sign-in.
Their tokens are not reused as authorization for the public Responses API.
The provider/configuration ID and saved model selection remain `openai_codex`.

Protocol tests use generated signing keys and synthetic credentials. They cover
a real loopback HTTP callback, PKCE binding, signed identity and consent,
registration reuse, account selection, refresh, revocation, account-specific
models and completed public Responses output. A real-account smoke test requires
the user to finish browser authorization and then complete a text request; mocked
tests alone do not establish real account eligibility.

Local verification on Windows / Python 3.11 (2026-10-27) completed official
browser authorization, returned eight account-listed models, and generated
`MoneyPrinterTurbo OAuth OK` through the existing LLM entrypoint using
`gpt-6.1-sol` and the public Responses API. Model access is account-specific;
this is a validation record, not a fixed supported-model list.
