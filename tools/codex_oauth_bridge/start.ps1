<#
.SYNOPSIS
    Start the host-side Codex OAuth bridge with a least-exposure network binding.

.DESCRIPTION
    Binds by default to the WSL/Docker vEthernet host IP rather than 0.0.0.0, so the
    bridge is reachable from containers via host.docker.internal but is NOT exposed on
    any physical LAN adapter (audit Finding F1). When a non-loopback address is used, a
    scoped Windows Firewall rule restricts inbound access to the Docker subnet only.
    The bearer token is required and is never generated or echoed here.
#>
[CmdletBinding()]
param(
    [int]    $Port            = 9876,
    # Empty => auto-detect the WSL vEthernet host IPv4. Pass 127.0.0.1 to force
    # loopback, or 0.0.0.0 to opt back into all-interfaces (discouraged).
    [string] $HostAddress     = '',
    [string] $CodexExecutable = 'codex',
    # Empty => derive from the WSL interface (e.g. 172.31.208.0/20). Scopes the
    # firewall rule's RemoteAddress so only the Docker subnet may connect.
    [string] $DockerSubnet    = '',
    [switch] $SkipFirewall
)

$ErrorActionPreference = 'Stop'
$FirewallRuleName = 'MoneyPrinterTurbo Codex Bridge'

function Get-WslInterface {
    Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.InterfaceAlias -match 'WSL' } |
        Select-Object -First 1
}

function Get-SubnetFromInterface {
    param($IpInfo)
    $bytes  = ([System.Net.IPAddress]::Parse($IpInfo.IPAddress)).GetAddressBytes()
    $prefix = [int]$IpInfo.PrefixLength
    $maskInt = if ($prefix -eq 0) { [uint32]0 } else { [uint32]([uint32]::MaxValue -shl (32 - $prefix)) }
    $ipInt = ([uint32]$bytes[0] -shl 24) -bor ([uint32]$bytes[1] -shl 16) -bor `
             ([uint32]$bytes[2] -shl 8)  -bor  [uint32]$bytes[3]
    $netInt = $ipInt -band $maskInt
    # Each element needs its own parens: PowerShell's comma binds looser than -band,
    # so `... -band 0xff, ...` would otherwise make 0xff,(...) the right operand.
    $netBytes = @(
        (($netInt -shr 24) -band 0xff), (($netInt -shr 16) -band 0xff),
        (($netInt -shr 8)  -band 0xff), ( $netInt          -band 0xff)
    )
    '{0}.{1}.{2}.{3}/{4}' -f $netBytes[0], $netBytes[1], $netBytes[2], $netBytes[3], $prefix
}

# --- Preflight: Codex CLI present and signed in via ChatGPT OAuth ------------
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

# --- Resolve bind address ----------------------------------------------------
if ([string]::IsNullOrWhiteSpace($HostAddress)) {
    $wsl = Get-WslInterface
    if (-not $wsl) {
        throw 'Could not auto-detect a WSL vEthernet IPv4 address. Is Docker Desktop running? ' +
              'Pass an explicit -HostAddress (e.g. 127.0.0.1, or the host IP the container reaches).'
    }
    $HostAddress = $wsl.IPAddress
    if ([string]::IsNullOrWhiteSpace($DockerSubnet)) {
        $DockerSubnet = Get-SubnetFromInterface -IpInfo $wsl
    }
}

$isLoopback = ($HostAddress -eq '127.0.0.1' -or $HostAddress -eq '::1')

if ($HostAddress -eq '0.0.0.0') {
    Write-Warning ('Binding to 0.0.0.0 exposes the bridge on ALL interfaces, including your LAN, ' +
                   'in cleartext HTTP. Prefer the WSL interface bind (leave -HostAddress empty).')
}

# --- Scoped firewall rule (defense-in-depth) ---------------------------------
if (-not $isLoopback -and -not $SkipFirewall) {
    if ([string]::IsNullOrWhiteSpace($DockerSubnet)) {
        throw "Cannot scope the firewall rule: -DockerSubnet is empty and could not be derived. " +
              "Pass -DockerSubnet (e.g. 172.31.208.0/20) or -SkipFirewall to manage it yourself."
    }
    # Creating a firewall rule requires an elevated session.
    $identity  = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object System.Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this script from an elevated (Administrator) PowerShell to create the scoped " +
              "firewall rule, or pass -SkipFirewall if you manage firewalling yourself."
    }
    # Remove-then-add for idempotency across restarts.
    Get-NetFirewallRule -DisplayName $FirewallRuleName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
    New-NetFirewallRule `
        -DisplayName $FirewallRuleName `
        -Direction Inbound -Action Allow -Protocol TCP `
        -LocalPort $Port -LocalAddress $HostAddress -RemoteAddress $DockerSubnet `
        -Profile Any | Out-Null
    Write-Host "Firewall: allowed TCP $HostAddress`:$Port from $DockerSubnet only (rule '$FirewallRuleName')."
    Write-Host "Teardown: Remove-NetFirewallRule -DisplayName '$FirewallRuleName'"
}
elseif ($isLoopback) {
    Write-Host 'Loopback bind: no firewall rule needed.'
}

# --- Launch the bridge -------------------------------------------------------
Write-Host "Starting Codex OAuth bridge on $HostAddress`:$Port ..."
python -m tools.codex_oauth_bridge.server `
    --host $HostAddress --port $Port --codex-executable $command.Source
