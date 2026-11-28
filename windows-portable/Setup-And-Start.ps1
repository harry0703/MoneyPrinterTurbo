# MoneyPrinterTurbo portable Windows prerequisite check and launcher.
# Put this file alongside start.bat and the MoneyPrinterTurbo and lib folders.
param([switch]$UpdateOnly)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$project = Join-Path $root 'MoneyPrinterTurbo'
if (-not (Test-Path (Join-Path $project 'webui\Main.py'))) { throw "MoneyPrinterTurbo\webui\Main.py is missing beside this setup file. Extract the complete portable archive first." }

function Test-Exe([string]$Path, [string]$Argument) {
    if (-not $Path -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $false }
    try { & $Path $Argument *> $null; return ($LASTEXITCODE -eq 0) } catch { return $false }
}
function Find-CommandPath([string]$Name) {
    $c = Get-Command $Name -ErrorAction SilentlyContinue | Where-Object Source | Select-Object -First 1
    if ($c) { return $c.Source }
    return $null
}
function Install-Winget([string]$Id) {
    if (-not (Find-CommandPath 'winget.exe')) { throw "winget is missing. Install Microsoft App Installer, or install $Id manually, then rerun this file." }
    Write-Host "Installing $Id with winget..."
    & winget install --id $Id --exact --source winget --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) { throw "winget could not install $Id (exit $LASTEXITCODE)." }
    $env:PATH = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' + [Environment]::GetEnvironmentVariable('Path','User') + ';' + $env:PATH
}

Write-Host 'Checking Python...'
$bundledPython = Join-Path $root 'lib\python\python.exe'
$venvPython = Join-Path $project '.venv\Scripts\python.exe'
$python = $null
if (Test-Exe $bundledPython '--version') { $python = $bundledPython }
elseif (Test-Exe $venvPython '--version') { $python = $venvPython }
else {
    $systemPython = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
        'C:\Program Files\Python311\python.exe'
    ) | Where-Object { Test-Exe $_ '--version' } | Select-Object -First 1
    if (-not $systemPython) {
        $candidate = Find-CommandPath 'python.exe'
        if (Test-Exe $candidate '--version') { $systemPython = $candidate }
    }
    if (-not $systemPython) {
        Install-Winget 'Python.Python.3.11'
        $systemPython = @(
            (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python311\python.exe'),
            'C:\Program Files\Python311\python.exe',
            (Find-CommandPath 'python.exe')
        ) | Where-Object { Test-Exe $_ '--version' } | Select-Object -First 1
    }
    if (-not $systemPython) { throw 'Python installation finished but python.exe was not located. Reopen PowerShell and rerun.' }
    if (-not (Test-Exe $venvPython '--version')) {
        Write-Host 'Creating isolated project Python environment...'
        & $systemPython -m venv (Join-Path $project '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create Python virtual environment.' }
    }
    $python = $venvPython
}
Write-Host "Python: $python"

if ($UpdateOnly) {
    $bundledGit = Join-Path $root 'lib\git\bin\git.exe'
    $git = if (Test-Exe $bundledGit '--version') { $bundledGit } else { Find-CommandPath 'git.exe' }
    if ((Test-Path (Join-Path $project '.git')) -and -not $git) {
        Install-Winget 'Git.Git'
        $git = Find-CommandPath 'git.exe'
        if (-not $git) { $git = 'C:\Program Files\Git\bin\git.exe' }
    }
    if (Test-Path (Join-Path $project '.git')) {
        if (-not (Test-Exe $git '--version')) { throw 'Git installation completed but git.exe was not located. Rerun update.bat.' }
        Write-Host 'Updating project source with git pull...'
        & $git -C $project pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw 'git pull failed. Existing local changes or network errors may need attention.' }
    } else { Write-Host 'No .git checkout found; skipping source update for this portable archive.' }
}


$req = Join-Path $project 'requirements.txt'
try { & $python -c 'import streamlit, moviepy' *> $null; $packagesReady = ($LASTEXITCODE -eq 0) } catch { $packagesReady = $false }
if (-not $packagesReady -or $UpdateOnly) {
    if (-not (Test-Path $req)) { throw 'requirements.txt is missing; extract the full project archive.' }
    Write-Host 'Installing missing Python packages from requirements.txt...'
    & $python -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) { & $python -m ensurepip --upgrade; if ($LASTEXITCODE -ne 0) { throw 'pip is unavailable.' } }
    & $python -m pip install -r $req
    if ($LASTEXITCODE -ne 0) { throw 'Python package installation failed. Check the errors above.' }
}

Write-Host 'Checking FFmpeg...'
$ffmpegCandidates = @(
    (Join-Path $root 'lib\ffmpeg\ffmpeg-7.0-essentials_build\ffmpeg.exe'),
    'C:\FFMPEG\bin\ffmpeg.exe',
    (Find-CommandPath 'ffmpeg.exe')
)
$ffmpeg = $ffmpegCandidates | Where-Object { Test-Exe $_ '-version' } | Select-Object -First 1
if (-not $ffmpeg) {
    Install-Winget 'Gyan.FFmpeg'
    $ffmpeg = @((Find-CommandPath 'ffmpeg.exe'), 'C:\FFMPEG\bin\ffmpeg.exe') | Where-Object { Test-Exe $_ '-version' } | Select-Object -First 1
    if (-not $ffmpeg) {
        $ffmpeg = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Filter ffmpeg.exe -File -Recurse -ErrorAction SilentlyContinue | Where-Object { Test-Exe $_.FullName '-version' } | Select-Object -ExpandProperty FullName -First 1
    }
}
if (-not $ffmpeg) { throw 'FFmpeg could not be located after installation. Reopen PowerShell and rerun.' }
Write-Host "FFmpeg: $ffmpeg"
$env:FFMPEG_BINARY = $ffmpeg
$env:PATH = (Split-Path $ffmpeg -Parent) + ';' + $env:PATH

$config = Join-Path $project 'config.toml'
if (-not (Test-Path $config)) {
    $example = Join-Path $project 'config.example.toml'
    if (Test-Path $example) { Copy-Item $example $config }
}
if (Test-Path $config) {
    $contents = [IO.File]::ReadAllText($config)
    $escapedPath = $ffmpeg.Replace('\','\\')
    $entry = 'ffmpeg_path = "' + $escapedPath + '"'
    $section = [regex]::Match($contents, '(?ms)^\[app\]\s*\r?\n(?<body>.*?)(?=^\[|\z)')
    if ($section.Success) {
        $body = $section.Groups['body'].Value
        if ($body -match '(?m)^\s*ffmpeg_path\s*=') { $newBody = [regex]::Replace($body, '(?m)^\s*ffmpeg_path\s*=.*$', $entry) }
        else { $newBody = $entry + [Environment]::NewLine + $body }
        $newContents = $contents.Substring(0,$section.Groups['body'].Index) + $newBody + $contents.Substring($section.Groups['body'].Index + $section.Groups['body'].Length)
    } else { $newContents = $contents.TrimEnd() + [Environment]::NewLine + '[app]' + [Environment]::NewLine + $entry + [Environment]::NewLine }
    if ($newContents -ne $contents) {
        Copy-Item $config ($config + '.before-setup.bak') -Force
        [IO.File]::WriteAllText($config,$newContents,[Text.UTF8Encoding]::new($false))
        Write-Host 'Saved FFmpeg path in config.toml (backup: config.toml.before-setup.bak).'
    }
}

if ($UpdateOnly) { Write-Host 'Requirements checked. Update complete.'; exit 0 }

Write-Host 'Starting MoneyPrinterTurbo...'
$env:PYTHONPATH = $project + ';' + $env:PYTHONPATH
Set-Location $project
& $python -m streamlit run (Join-Path $project 'webui\Main.py') --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=False
exit $LASTEXITCODE
