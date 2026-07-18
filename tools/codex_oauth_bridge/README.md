# Codex OAuth host bridge (Windows)

This bridge lets MoneyPrinterTurbo use the **standalone Codex CLI** after you
authenticate it with your ChatGPT account. It uses Codex OAuth only: do not
enter an OpenAI API key for this provider.

The bridge is an authenticated local service, not an internet-facing API.
Keep it on the host running Codex and do not expose port `9876` through a
router, reverse proxy, tunnel, or public firewall rule.

## Before you start

Use the standalone npm package. A packaged Microsoft Store `codex` alias can
be inaccessible to PowerShell or resolve differently, so do not rely on that
alias for this bridge:

```powershell
npm install -g @openai/codex
codex login
```

Complete the browser sign-in flow, then confirm that the standalone CLI is
signed in:

```powershell
codex login status
```

Never paste `auth.json`, browser cookies, OAuth tokens, or copied browser
session data into MoneyPrinterTurbo. The bridge uses the logged-in CLI on this
machine; its **bridge token** is a separate local shared secret, not an OAuth
credential.

## Start the bridge

Run the following from the MoneyPrinterTurbo repository root in one PowerShell
window. This prompts without putting the token in your PowerShell command
history and sets `CODEX_BRIDGE_TOKEN` for this PowerShell session only.

```powershell
$secureToken = Read-Host 'Enter a high-entropy bridge token' -AsSecureString
$tokenBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
try {
    $env:CODEX_BRIDGE_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($tokenBstr)
}
finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($tokenBstr)
    Remove-Variable tokenBstr -ErrorAction SilentlyContinue
    Remove-Variable secureToken -ErrorAction SilentlyContinue
}

.\tools\codex_oauth_bridge\start.ps1 -HostAddress 127.0.0.1
```

The default launcher arguments are `-Port 9876`, `-HostAddress 0.0.0.0`, and
`-CodexExecutable codex`. Use `127.0.0.1` for a native, host-only
MoneyPrinterTurbo process. The launcher does not generate, print, log, or save
the bridge token.

Verify the host-only bridge from a second PowerShell window:

```powershell
Invoke-WebRequest http://127.0.0.1:9876/health
```

The expected response has `status` set to `ok`. Stop the bridge with `Ctrl+C`;
closing the PowerShell window also clears its session-only
`CODEX_BRIDGE_TOKEN`.

If PowerShell says that running scripts is disabled, allow this local script
for the current PowerShell process only, then run the launcher again:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

This does not change the machine or user policy. If an organization-managed
policy still blocks the command, ask its administrator rather than weakening a
machine-wide policy.

### Docker Desktop

Docker containers reach the Windows host through `host.docker.internal`. Start
the bridge first, bound to all host interfaces so Docker Desktop can reach it:

```powershell
.\tools\codex_oauth_bridge\start.ps1 -HostAddress 0.0.0.0
```

Then, in another PowerShell window at the repository root, start
MoneyPrinterTurbo:

```powershell
docker compose up
```

The required order is: sign in with `codex login`; set the session-only bridge
token; start and health-check the bridge; start Docker; then configure the
provider in the WebUI. Do not publish bridge port `9876` in a Compose file.

Binding to `0.0.0.0` is only for Docker Desktop host access. Keep Windows
Firewall from accepting public or internet traffic to TCP `9876`; if a rule is
necessary, scope it to the Private/local network only. Do not add port
forwarding, a tunnel, or a reverse proxy. If Docker Desktop cannot reach the
bridge under this restriction, review the Docker Desktop network profile and
Firewall rule scope rather than opening the bridge to the internet.

## Configure MoneyPrinterTurbo

In **Settings**, choose **Codex (ChatGPT OAuth)** and use these fields:

| Field | Value |
| --- | --- |
| Base Url (Docker) | `http://host.docker.internal:9876` |
| Base Url (native host process) | `http://127.0.0.1:9876` |
| Codex Bridge Token | The exact same local bridge token set for `CODEX_BRIDGE_TOKEN` |
| Codex Bridge Timeout | `300` seconds, or a value from 30 to 900 |
| Model Name | Optional; leave blank to let Codex choose |
| API Key | Not used; this provider has no API-key field |

The bridge token is required for every generation request. Treat it like a
local password and do not include it in screenshots, issue reports, logs, or
shell history.

## Error guide

| Symptom | Meaning and action |
| --- | --- |
| `Standalone Codex CLI not found...` | Install the standalone CLI with `npm install -g @openai/codex`, open a new PowerShell window, and retry. |
| `Codex is not signed in...` | Run `codex login` in the same Windows account, then retry. |
| `Set CODEX_BRIDGE_TOKEN...` | Set a high-entropy bridge token in the current PowerShell session and restart the launcher. |
| PowerShell says running scripts is disabled | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` for this session only, then retry. |
| Health check cannot connect | Start the bridge first; verify the host and port, and keep the bridge PowerShell window open. |
| WebUI reports `401` / `Invalid bridge token` | Re-enter the same bridge token in the Codex Bridge Token field. Do not substitute OAuth data. |
| WebUI reports `429` / `busy` | One generation is already running; wait for it to finish and retry. |
| WebUI reports `502` | The local Codex CLI failed; check that `codex login status` succeeds without sharing its credential files or output that contains secrets. |
| WebUI reports `504` / `timeout` | Increase the Codex Bridge Timeout within the 30–900 second range, or shorten the request. |
