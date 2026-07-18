[CmdletBinding()]
param(
    [int]$Port = 9876,
    [string]$HostAddress = '0.0.0.0',
    [string]$CodexExecutable = 'codex'
)

$ErrorActionPreference = 'Stop'

$command = Get-Command $CodexExecutable -ErrorAction SilentlyContinue
if (-not $command) {
    throw 'Standalone Codex CLI not found. Install it with: npm install -g @openai/codex'
}

$loginStatus = (& $CodexExecutable login status 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $loginStatus -ne 'Logged in using ChatGPT') {
    throw 'Codex must be signed in using ChatGPT OAuth. Run: codex login'
}

if (-not $env:CODEX_BRIDGE_TOKEN) {
    throw 'Set CODEX_BRIDGE_TOKEN to a high-entropy local bridge token before starting.'
}

python -m tools.codex_oauth_bridge.server `
    --host $HostAddress --port $Port --codex-executable $command.Source
