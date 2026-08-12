param(
    [switch]$CreateFolders,
    [string]$VoiceboxBaseUrl = "http://127.0.0.1:17493",
    [string]$ChatterboxBaseUrl = "http://127.0.0.1:4123/v1",
    [string]$WorkspaceRoot
)

$ErrorActionPreference = "Stop"

if (-not $WorkspaceRoot) {
    $WorkspaceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string]$Name,
        [string]$Status,
        [string]$Detail
    )

    $checks.Add([pscustomobject]@{
        Name = $Name
        Status = $Status
        Detail = $Detail
    }) | Out-Null
}

function Test-CommandAvailable {
    param([string]$CommandName)

    $cmd = Get-Command $CommandName -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    return $null
}

function Invoke-ToolText {
    param(
        [string]$FileName,
        [string[]]$Arguments
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $script:ErrorActionPreference = "Continue"
        $output = & $FileName @Arguments 2>&1
        return (($output | ForEach-Object { $_.ToString() }) -join " ").Trim()
    }
    catch {
        return $_.Exception.Message
    }
    finally {
        $script:ErrorActionPreference = $previousErrorActionPreference
    }
}

function Test-HttpEndpoint {
    param(
        [string]$Name,
        [string]$Url
    )

    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Add-Check $Name "PASS" ("Reachable: HTTP {0} at {1}" -f [int]$response.StatusCode, $Url)
    }
    catch {
        Add-Check $Name "WARN" ("Not reachable at {0}. Start the local app/server first if you plan to use it. {1}" -f $Url, $_.Exception.Message)
    }
}

Write-Host "Local voice workflow readiness check"
Write-Host ("Workspace: {0}" -f $WorkspaceRoot)
Write-Host ""

if ($CreateFolders) {
    $folders = @(
        "local_voice",
        "local_voice\reference",
        "local_voice\scripts",
        "local_voice\output"
    )

    foreach ($folder in $folders) {
        $path = Join-Path $WorkspaceRoot $folder
        if (-not (Test-Path $path)) {
            New-Item -ItemType Directory -Path $path | Out-Null
        }
    }

    Add-Check "Local folders" "PASS" "Ensured local_voice/reference, local_voice/scripts, and local_voice/output exist."
}
else {
    $localVoicePath = Join-Path $WorkspaceRoot "local_voice"
    if (Test-Path $localVoicePath) {
        Add-Check "Local folders" "PASS" "local_voice folder exists."
    }
    else {
        Add-Check "Local folders" "WARN" "local_voice folder not found. Re-run with -CreateFolders."
    }
}

try {
    $os = Get-CimInstance Win32_OperatingSystem
    $memoryGb = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
    Add-Check "Windows" "PASS" ("{0}; RAM: {1} GB" -f $os.Caption, $memoryGb)
}
catch {
    Add-Check "Windows" "WARN" ("Could not read OS/RAM details: {0}" -f $_.Exception.Message)
}

try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    Add-Check "CPU" "PASS" ("{0}; {1} cores / {2} logical processors" -f $cpu.Name.Trim(), $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
}
catch {
    Add-Check "CPU" "WARN" ("Could not read CPU details: {0}" -f $_.Exception.Message)
}

$python = Test-CommandAvailable "python"
if ($python) {
    $version = Invoke-ToolText "python" @("--version")
    Add-Check "Python" "PASS" ("{0} ({1})" -f $version, $python)
}
else {
    $pyLauncher = Test-CommandAvailable "py"
    if ($pyLauncher) {
        $version = Invoke-ToolText "py" @("--version")
        Add-Check "Python" "PASS" ("{0} via py launcher ({1})" -f $version, $pyLauncher)
    }
    else {
        Add-Check "Python" "WARN" "Python was not found on PATH. Voicebox may not need it, but direct engines and MoneyPrinterTurbo development do."
    }
}

$uv = Test-CommandAvailable "uv"
if ($uv) {
    $version = Invoke-ToolText "uv" @("--version")
    Add-Check "uv" "PASS" ("{0} ({1})" -f $version, $uv)
}
else {
    Add-Check "uv" "WARN" "uv was not found on PATH. This is fine for Voicebox, but useful for MoneyPrinterTurbo and Python-based engines."
}

$ffmpeg = Test-CommandAvailable "ffmpeg"
if ($ffmpeg) {
    $version = Invoke-ToolText "ffmpeg" @("-version")
    $version = ($version -split "\r?\n" | Select-Object -First 1) -join " "
    Add-Check "FFmpeg" "PASS" ("{0} ({1})" -f $version, $ffmpeg)
}
else {
    Add-Check "FFmpeg" "WARN" "ffmpeg was not found on PATH. MoneyPrinterTurbo may auto-detect/download it, but manual audio conversion will be easier with FFmpeg installed."
}

$docker = Test-CommandAvailable "docker"
if ($docker) {
    $version = Invoke-ToolText "docker" @("--version")
    if ($version -match "access is denied|error loading config|denied") {
        Add-Check "Docker" "WARN" ("Docker is installed but could not read its config cleanly: {0}" -f $version)
    }
    else {
        Add-Check "Docker" "PASS" ("{0} ({1})" -f $version, $docker)
    }
}
else {
    Add-Check "Docker" "WARN" "Docker was not found on PATH. Only needed if you choose a Docker-based Chatterbox server."
}

$configExample = Join-Path $WorkspaceRoot "config.example.toml"
if (Test-Path $configExample) {
    $configText = Get-Content $configExample -Raw
    if ($configText -match "\[chatterbox\]") {
        Add-Check "MoneyPrinterTurbo Chatterbox config" "PASS" "config.example.toml includes a [chatterbox] section."
    }
    else {
        Add-Check "MoneyPrinterTurbo Chatterbox config" "WARN" "No [chatterbox] section found in config.example.toml."
    }
}
else {
    Add-Check "MoneyPrinterTurbo config" "WARN" "config.example.toml was not found."
}

Test-HttpEndpoint "Voicebox API" ($VoiceboxBaseUrl.TrimEnd("/") + "/models/status")
Test-HttpEndpoint "Chatterbox API" ($ChatterboxBaseUrl.TrimEnd("/") + "/models")

Write-Host "Results"
foreach ($check in $checks) {
    $color = "White"
    if ($check.Status -eq "PASS") { $color = "Green" }
    elseif ($check.Status -eq "WARN") { $color = "Yellow" }
    elseif ($check.Status -eq "FAIL") { $color = "Red" }

    Write-Host ("[{0}] {1}: {2}" -f $check.Status, $check.Name, $check.Detail) -ForegroundColor $color
}

Write-Host ""
Write-Host "No models were downloaded and no audio was generated."
