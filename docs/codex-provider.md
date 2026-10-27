# OpenAI - Codex

Select **OpenAI - Codex** in the LLM provider settings and choose **Connect ChatGPT
with a code**. Open the OpenAI authorization page, enter the displayed code and
approve access. The UI polls for confirmation automatically. Device-code sign-in
must be enabled for the account. Use **Test LLM Connection** after connecting and
selecting a model.

This provider uses the Codex allowance of the connected ChatGPT subscription for
text generation. Voice and video generation still use their separately configured
providers. No API key, Codex CLI installation or shared CLI credentials are needed.

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
