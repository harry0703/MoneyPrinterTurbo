[CmdletBinding()]
param(
    [string]$OutputRoot,
    [Parameter(Mandatory = $true)]
    [string]$MediaToolsDirectory,
    [switch]$SkipArchive
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Invoke-BuildCommand {
    param([string]$Program, [string[]]$Arguments)

    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program exited with code $LASTEXITCODE"
    }
}

function Copy-Directory {
    param([string]$Source, [string]$Destination, [string[]]$Exclude = @())

    # 保留运行时的目录结构，同时避免打包编译缓存。
    & robocopy.exe $Source $Destination /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP /XF '*.pyc' /XD __pycache__ @Exclude
    if ($LASTEXITCODE -ge 8) {
        throw "Robocopy failed for $Source with code $LASTEXITCODE"
    }
}

if ($env:OS -ne 'Windows_NT') {
    throw 'Run this script on Windows with the MSVC x64 toolchain installed.'
}

$project = Split-Path -Parent $PSScriptRoot
$build = Join-Path $project 'storage\desktop\windows-x64'
if (-not $OutputRoot) {
    $OutputRoot = Join-Path $build 'dist'
}
$OutputRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputRoot)
$media = (Resolve-Path -LiteralPath $MediaToolsDirectory).Path
foreach ($file in 'ffmpeg.exe', 'ffprobe.exe') {
    if (-not (Test-Path -LiteralPath (Join-Path $media $file) -PathType Leaf)) {
        throw "Missing $file in $media"
    }
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$crt = & $vswhere -latest -products '*' -find 'VC\Redist\MSVC\**\x64\Microsoft.VC143.CRT\msvcp140.dll' |
    Where-Object { $_ -notmatch '\\onecore\\' } | Select-Object -First 1
if (-not $crt) {
    throw 'Visual Studio x64 redistributable runtime was not found.'
}
$crtDirectory = Split-Path -Parent $crt

Push-Location $project
try {
    New-Item -ItemType Directory -Force $build | Out-Null
    $env:UV_NO_REGISTRY = '1'
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $build 'build-venv'
    $env:CARGO_TARGET_DIR = Join-Path $build 'target'
    $pythonRequest = '3.11-windows-x86_64'
    Invoke-BuildCommand 'uv' @('python', 'install', $pythonRequest, '--no-bin')
    $basePython = & uv python find --managed-python $pythonRequest
    if ($LASTEXITCODE -ne 0 -or -not $basePython) {
        throw 'Could not find the managed Windows x64 Python runtime.'
    }
    if ((& $basePython -I -c 'import sysconfig; print(sysconfig.get_platform())') -ne 'win-amd64') {
        throw 'The packaged Python interpreter must be Windows x64.'
    }
    Invoke-BuildCommand 'uv' @('sync', '--frozen', '--no-dev', '--no-editable', '--reinstall-package', 'mpt', '--python', $basePython)

    $target = 'x86_64-pc-windows-msvc'
    $manifest = Join-Path $PSScriptRoot 'src-tauri\Cargo.toml'
    Invoke-BuildCommand 'cargo' @('build', '--locked', '--release', '--target', $target, '--manifest-path', $manifest)

    $packageName = 'MoneyPrinterTurbo-windows-x64-' + (Get-Date -Format 'yyyyMMdd-HHmmssfff')
    $publish = Join-Path $OutputRoot $packageName
    $staging = Join-Path $OutputRoot ('.building-' + $packageName)
    $bundleName = 'MoneyPrinterTurbo'
    $bundle = Join-Path $staging $bundleName
    $runtimeDestination = Join-Path $bundle 'python'
    $toolsDestination = Join-Path $bundle 'tools'
    New-Item -ItemType Directory -Force $runtimeDestination, $toolsDestination | Out-Null

    $venvPython = Join-Path $env:UV_PROJECT_ENVIRONMENT 'Scripts\python.exe'
    $runtime = & $venvPython -I -c 'import sys; print(sys.base_prefix)'
    $packages = & $venvPython -I -c "import sysconfig; print(sysconfig.get_path('purelib'))"
    if (-not $runtime -or -not $packages) {
        throw 'Could not find the Python runtime or locked packages.'
    }
    Copy-Directory $runtime $runtimeDestination @((Join-Path $runtime 'Lib\site-packages'))
    $siteDestination = Join-Path $runtimeDestination 'Lib\site-packages'
    Copy-Directory $packages $siteDestination
    if (-not (Test-Path -LiteralPath (Join-Path $runtimeDestination 'python.exe')) -or
        -not (Test-Path -LiteralPath (Join-Path $siteDestination 'webui\Main.py'))) {
        throw 'The bundle is missing the Python interpreter or the WebUI.'
    }
    Get-ChildItem $siteDestination -Directory -Filter 'mpt-*.dist-info' | ForEach-Object {
        $metadata = Join-Path $_.FullName 'direct_url.json'
        if (Test-Path -LiteralPath $metadata) {
            Remove-Item -LiteralPath $metadata
        }
    }

    # 从 Visual Studio 的可再发行目录复制 DLL，应用和 Python 分别就地加载。
    Copy-Item (Join-Path $crtDirectory '*.dll') -Destination $bundle -Force
    Copy-Item (Join-Path $crtDirectory '*.dll') -Destination $runtimeDestination -Force
    Copy-Item (Join-Path $PSScriptRoot 'backend.py') -Destination $bundle
    foreach ($file in 'ffmpeg.exe', 'ffprobe.exe') {
        Copy-Item -LiteralPath (Join-Path $media $file) -Destination $toolsDestination
    }
    $mediaLicense = Join-Path (Split-Path -Parent $media) 'LICENSE'
    if (Test-Path -LiteralPath $mediaLicense -PathType Leaf) {
        Copy-Item -LiteralPath $mediaLicense -Destination (Join-Path $toolsDestination 'FFmpeg-LICENSE.txt')
    }
    $exe = Join-Path $env:CARGO_TARGET_DIR "$target\release\mpt-desktop.exe"
    Copy-Item -LiteralPath $exe -Destination (Join-Path $bundle 'MoneyPrinterTurbo.exe')

    $archiveName = 'MoneyPrinterTurbo-windows-x64.zip'
    if (-not $SkipArchive) {
        $archive = Join-Path $staging $archiveName
        Invoke-BuildCommand 'tar.exe' @('-a', '-cf', $archive, '-C', $staging, $bundleName)
    }
    Rename-Item -LiteralPath $staging -NewName $packageName
    Write-Output "APP=$publish\$bundleName\MoneyPrinterTurbo.exe"
    if (-not $SkipArchive) {
        Write-Output "ZIP=$publish\$archiveName"
    }
} finally {
    Pop-Location
}
