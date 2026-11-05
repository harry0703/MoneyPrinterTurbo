# OpenAI - ChatGPT (Native OAuth)

This optional provider registers MoneyPrinterTurbo using OpenAI's official
[Sign in with ChatGPT flow](https://developers.openai.com/siwc/token-sharing-open-source/sign-in).
Select **OpenAI - ChatGPT (Native OAuth)** explicitly in LLM settings. Its
configuration ID is `openai_chatgpt`; it uses the authorized ChatGPT plan through
public `/v1/models` and `/v1/responses` endpoints without an API key or Codex CLI.

## Compatibility and eligibility

The existing **OpenAI - Codex** (`openai_codex`) provider keeps its device-code
sign-in, model catalog, configuration keys and credentials. Upgrading does not
select native OAuth, reinterpret device credentials, or require existing Codex
users to sign in again. The two providers have independent model settings.

Native OAuth requires an eligible account/workspace and permission to use its
ChatGPT plan. An account that works with the device-code provider may be unable
to authorize this separate flow. A consent page with disabled Continue cannot
necessarily be fixed by signing in again. Do not infer eligibility from the plan
name alone or treat a single account's result as applying to all Free accounts.
See OpenAI's [eligibility and recovery guidance](https://developers.openai.com/siwc/token-sharing-open-source/errors-and-recovery).

If native authorization is unavailable, select another provider explicitly.
Neither authorization nor inference failures switch to Codex or API-key billing.
Native sign-in, cancellation and disconnect never modify device-flow credentials.

## Local sign-in

1. Run MoneyPrinterTurbo and select **OpenAI - ChatGPT (Native OAuth)**.
2. Choose **Continue with ChatGPT**, then open the OpenAI authorization page.
3. Sign in and authorize this application. The browser returns to a temporary
   `http://127.0.0.1:<port>/auth/callback` listener owned by the Python process.
4. Return to settings, select an account-listed model, and test the connection
   or generate a script and search terms.

The browser and Python runtime must run on the same computer. This implementation
has no remote callback forwarding or credential transfer for Docker/remote VMs.
Selecting native OAuth in a remotely accessed WebUI does not make the callback
reachable. Use the separately available Codex provider where that flow works,
or explicitly configure another provider. Voice and video services remain
separately configured.

## Registrations and storage

Initial registration uses `dynamic_agent_client`, the application name and a
stable installation host ID. Later sign-ins reuse the issued client ID. Each
attempt uses fresh state, nonce and PKCE. ID-token signatures, issuer, audience,
expiry, nonce and returning identity are verified. Inference requires the granted
`chatgpt.tokens.use.direct` scope.

The stores under the runtime root (`MPT_HOME` when set) are separate:

| Provider | Credential file | Model configuration |
| --- | --- | --- |
| Codex device code | `storage/auth/openai_codex.bin` | `openai_codex_model_name` |
| ChatGPT native OAuth | `storage/auth/openai_chatgpt.bin` | `openai_chatgpt_model_name` |

Windows uses user-scoped DPAPI; Unix writes use private permissions. Native
writes are atomic. Discovery/JWKS run before taking the refresh critical section;
the rotating-token exchange and persistence stay serialized across processes.
After obtaining the lock, a waiter reloads the latest credentials instead of
refreshing the old token again. Lock contention is recoverable and does not clear
credentials. Account controls have a short bounded lock wait and a retry action;
request paths share their remaining time budget with refresh and lock waits.

**Disconnect ChatGPT** attempts revocation and clears the selected native
account's tokens while retaining its registration/host identity. If revocation
cannot be confirmed, check the connected application in ChatGPT settings.

### Users of the earlier PR preview

Commit `8bab424` stored native v2 credentials at the old Codex path. Users who
actually tried that preview can explicitly copy that record with:

```shell
uv run python scripts/accept_chatgpt_oauth.py --import-preview
```

Import requires a valid v2 native record and an absent native destination. It
preserves the registration and host ID, never converts device credentials, never
overwrites an existing native store, and retains the source file. The command
then runs model and generation checks against the imported account; normal
upgrades do not need it. For an import without inference, call
`chatgpt_auth.import_preview_credentials()` from a local Python session.

After a successful import, the earlier preview's file still occupies the Codex
path. If using the original Codex provider again, use its disconnect control to
clear that preview record and then complete device-code sign-in. A device token
already overwritten by the earlier preview cannot be reconstructed. No provider
configuration is switched automatically.

## Reproducible real-account acceptance

The manual script runs the real project entrypoints with a fixed, non-sensitive
walking-video topic. It is not part of unattended CI and consumes the selected
account's ChatGPT plan allowance. On a local machine with an eligible account:

```shell
uv run python scripts/accept_chatgpt_oauth.py --login --disconnect
```

Optionally pass `--model <account-listed-slug>` and `--output <report.json>`.
Without `--model`, the first returned model is used. The default report path is
`storage/acceptance/chatgpt-native-<UTC timestamp>.json`. The script does not
change `config.toml` or fall back to another provider. `--disconnect` revokes and
clears the active native session after successful inference checks.

The report contains:

- UTC timestamp, OS/Python, commit and whether the checkout has local changes;
- whether browser authorization ran and plan permission was granted;
- account-listed model IDs and the selected model;
- real `llm.generate_script` and `llm.generate_terms` output, HTTP status,
  request IDs when supplied, and `response.completed` metadata;
- forced refresh, registration continuity and a completed post-refresh request;
- revocation confirmation, local token clearing and rejection of signed-out
  inference without sending an API request.

Missing request/response IDs are recorded as `null`, never invented. Token
responses, identity claims, authorization URLs/codes, PKCE values, cookies and
arbitrary headers are not exported. Request diagnostics are disabled for this
script; its optional trace uses an allowlist of API metadata. A run without a
fresh browser login or without disconnect is labeled `partial`, not a full pass.
If the account cannot authorize, the report records failure without changing
other providers. Complete a new run after implementation changes; earlier preview
acceptance is not evidence of the revised provider's live behavior.

## Automated regressions

Run the original Codex tests and the new native tests together. Native tests use
synthetic credentials and signed identities. The concurrency suite starts
independent Python interpreters and a slow local HTTP server to check that the
UI recovers, failed waits preserve credentials, deadlines are bounded, and a
contended rotating token is exchanged only once. Acceptance-script tests exercise
the real LLM entrypoints over synthetic HTTP responses and check report redaction;
they do not establish eligibility or live API access.

## Recorded local acceptance

[Windows / Python 3.11.15, 2026-10-27](validation/chatgpt-native-oauth-windows-2026-10-27.json)
records a fresh browser authorization, eight account-listed models, completed
script/keyword generation using `gpt-6.1-sol`, refresh and a completed follow-up
request, confirmed revocation, and a blocked signed-out request. Response IDs are
included; the `x-request-id` header was absent and is recorded as `null`.

The generated script also rendered to an 18.47-second 1080p video using local
test footage, silent mode and subtitles, with a successful full decode check.
External TTS and stock-media services were not exercised. Browser checks covered
provider separation and signed-out settings, while the live model/inference
checks ran through the acceptance script and real project LLM entrypoints.
This was an uncommitted working tree based on `8bab424`; the report includes
source-file hashes to identify the tested implementation.
