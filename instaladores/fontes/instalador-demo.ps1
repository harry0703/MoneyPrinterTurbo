# ------------------------------------------------------------
#  (c) 2026 THM TECNOLOGIA. Distribuido sob licenca MIT;
#  Autoria, engenharia e auditoria: THM TECNOLOGIA
#  Pacote oficial de instalacao e distribuicao do
#  MoneyPrinterTurbo (software base sob licenca MIT).
#  a manutencao deste aviso de autoria e obrigatoria.
# ------------------------------------------------------------
# ============================================================
#  MONEYPRINTERTURBO - INSTALADOR COMPLETO (fluxo unico)
#  Faz TUDO em uma execucao: Python, programa, dependencias,
#  chaves, modo aplicativo, icone e abre a interface no final.
# ============================================================
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

$installDir = Join-Path $env:USERPROFILE 'MoneyPrinterTurbo'
$zipUrl = 'https://codeload.github.com/ThalesAndrades/MoneyPrinterTurbo/zip/refs/heads/main'
$pyUrl  = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'

function Step([int]$n, [string]$msg) {
  Write-Host ''
  Write-Host ("  PASSO $n de 6  -  $msg") -ForegroundColor Cyan
  Write-Host ('  ' + ('-' * 54)) -ForegroundColor DarkGray
}
function Ok([string]$msg)   { Write-Host ("  [OK] " + $msg) -ForegroundColor Green }
function Info([string]$msg) { Write-Host ("  " + $msg) -ForegroundColor Gray }

function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
              [Environment]::GetEnvironmentVariable('Path','User')
}

function Test-PyVersion([string]$exe) {
  try {
    & $exe -c "import sys; sys.exit(0 if sys.version_info[:2] in ((3,11),(3,12)) else 1)" 2>$null
    return ($LASTEXITCODE -eq 0)
  } catch { return $false }
}

function Find-Python {
  $cands = @()
  foreach ($v in @('-3.12','-3.11')) {
    try { $p = (& py $v -c "import sys; print(sys.executable)" 2>$null); if ($p) { $cands += $p.Trim() } } catch {}
  }
  $cands += @(
    (Join-Path $env:LocalAppData 'Programs\Python\Python312\python.exe'),
    (Join-Path $env:LocalAppData 'Programs\Python\Python311\python.exe'),
    'C:\Python312\python.exe', 'C:\Python311\python.exe'
  )
  try { $w = (Get-Command python -ErrorAction SilentlyContinue).Source; if ($w) { $cands += $w } } catch {}
  foreach ($c in $cands) { if ($c -and (Test-Path $c) -and (Test-PyVersion $c)) { return $c } }
  return $null
}

try {
  Write-Host ''
  Write-Host '  ========================================================' -ForegroundColor Green
  Write-Host '     MONEYPRINTERTURBO - VERSAO DEMONSTRACAO (DEMO)' -ForegroundColor Green
  Write-Host '     Experimente gratis. Versao BR Completa: thales@thmtecnologia.com' -ForegroundColor Green
  Write-Host '  ========================================================' -ForegroundColor Green

  # ============ PASSO 1: PYTHON ============
  Step 1 'Verificando o Python (motor do programa)'
  $py = Find-Python
  if (-not $py) {
    Info 'Python 3.11/3.12 nao encontrado. Instalando automaticamente...'
    $wingetOk = $false
    if (Get-Command winget -ErrorAction SilentlyContinue) {
      try {
        & winget install --id Python.Python.3.12 -e --accept-source-agreements --accept-package-agreements --silent
        Refresh-Path
        $py = Find-Python
        if ($py) { $wingetOk = $true }
      } catch {}
    }
    if (-not $wingetOk) {
      Info 'Baixando o Python direto do site oficial (python.org)...'
      $pyExe = Join-Path $env:TEMP 'python-setup.exe'
      Invoke-WebRequest -Uri $pyUrl -OutFile $pyExe -UseBasicParsing
      Info 'Instalando o Python (sem precisar de cliques)...'
      Start-Process -FilePath $pyExe -ArgumentList '/quiet','InstallAllUsers=0','PrependPath=1','Include_launcher=1' -Wait
      Remove-Item $pyExe -Force -ErrorAction SilentlyContinue
      Refresh-Path
      $py = Find-Python
    }
    if (-not $py) { throw 'Nao consegui instalar o Python automaticamente. Instale o Python 3.12 em python.org e rode este instalador de novo.' }
  }
  Ok ("Python pronto: " + $py)

  # ============ PASSO 2: BAIXAR O PROGRAMA ============
  Step 2 'Baixando o MoneyPrinterTurbo'
  if (Test-Path (Join-Path $installDir 'webui\Main.py')) {
    Ok 'Programa ja baixado anteriormente. Mantendo.'
  } else {
    $zip = Join-Path $env:TEMP 'mpt.zip'
    Info 'Baixando do GitHub (sem precisar de Git)...'
    Invoke-WebRequest -Uri $zipUrl -OutFile $zip -UseBasicParsing
    Info 'Extraindo os arquivos...'
    $tmpx = Join-Path $env:TEMP 'mpt_extract'
    if (Test-Path $tmpx) { Remove-Item $tmpx -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $tmpx -Force
    $inner = Get-ChildItem $tmpx -Directory | Select-Object -First 1
    if (-not (Test-Path $installDir)) { New-Item -ItemType Directory -Path $installDir | Out-Null }
    Copy-Item (Join-Path $inner.FullName '*') $installDir -Recurse -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Remove-Item $tmpx -Recurse -Force -ErrorAction SilentlyContinue
    Ok ('Programa instalado em ' + $installDir)
  }

  # ============ PASSO 3: DEPENDENCIAS ============
  Step 3 'Instalando as dependencias (a parte mais demorada)'
  $venvPy = Join-Path $installDir '.venv\Scripts\python.exe'
  if (-not (Test-Path $venvPy)) {
    Info 'Criando ambiente isolado (.venv)...'
    & $py -m venv (Join-Path $installDir '.venv')
  }
  $marker = Join-Path $installDir '.venv\.deps_ok'
  if (Test-Path $marker) {
    Ok 'Dependencias ja instaladas anteriormente.'
  } else {
    Info 'Baixando e instalando pacotes. Pode levar 5 a 15 minutos.'
    Info 'Acompanhe o progresso abaixo - e normal aparecer muito texto:'
    Write-Host ''
    & $venvPy -m pip install --upgrade pip --quiet
    & $venvPy -m pip install -r (Join-Path $installDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'A instalacao das dependencias falhou. Veja as mensagens acima e rode o instalador de novo.' }
    Set-Content -Path $marker -Value 'ok'
    Ok 'Todas as dependencias instaladas.'
  }

  # ============ PASSO 4: CONFIGURACAO DA VERSAO DEMO ============
  Step 4 'Configurando a versao DEMO'
  $cfg = Join-Path $installDir 'config.toml'
  if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $installDir 'config.example.toml') $cfg
  }
  $cfgText = Get-Content -Raw $cfg
  $cfgText = $cfgText -replace [regex]::Escape('llm_provider = "openai"'), 'llm_provider = "pollinations"'
  $cfgText = $cfgText -replace [regex]::Escape('hide_config = false'), 'hide_config = true'
  if ($cfgText -notmatch 'language = "pt"') {
    $cfgText = $cfgText -replace [regex]::Escape('[ui]'), ('[ui]' + [Environment]::NewLine + 'language = "pt"')
  }
  Set-Content -Path $cfg -Value $cfgText
  if ($cfgText.Contains('pexels_api_keys = []')) {
    Info 'Abrindo a pagina do Pexels (chave gratuita para os videos de fundo)...'
    Start-Process 'https://www.pexels.com/api/'
    $pexels = [Microsoft.VisualBasic.Interaction]::InputBox(
      "CHAVE DO PEXELS (gratuita)`n`nA pagina do Pexels abriu no navegador.`nCrie a conta, copie sua API Key e cole aqui.`n`nSe quiser fazer depois, deixe em branco e clique OK.",
      'MoneyPrinterTurbo DEMO - Chave do Pexels', '')
    if ($pexels.Trim()) {
      (Get-Content -Raw $cfg) -replace [regex]::Escape('pexels_api_keys = []'), ('pexels_api_keys = ["' + $pexels.Trim() + '"]') | Set-Content $cfg
      Ok 'Chave do Pexels salva.'
    }
  }
  Ok 'DEMO configurada: roteiros via Pollinations (gratuito), interface em portugues.'
  Info 'Na versao BR Completa: todos os provedores de IA liberados, uso pelo'
  Info 'iPhone (em casa e via 4G/5G), instalacao assistida e suporte THM.'

  # Aviso de contato na Area de Trabalho
  $nota = Join-Path ([Environment]::GetFolderPath('Desktop')) 'VERSAO BR COMPLETA - THM TECNOLOGIA.txt'
  $msg = @(
    '==========================================================',
    '  MONEYPRINTERTURBO - VERSAO DEMO instalada com sucesso!',
    '==========================================================',
    '',
    'O que a DEMO inclui:',
    '  - Geracao de videos com narracao e legendas em portugues',
    '  - Roteiros por IA gratuita (Pollinations)',
    '  - Aplicativo com icone e bandeja do sistema',
    '',
    'A FERRAMENTA BR COMPLETA inclui tambem:',
    '  - Todos os provedores de IA (OpenAI, Gemini, DeepSeek...)',
    '  - Painel de configuracoes liberado',
    '  - Uso pelo iPhone/iPad em casa (QR Code) e em qualquer',
    '    lugar via 4G/5G (acesso remoto seguro)',
    '  - Instalacao assistida e suporte da THM TECNOLOGIA',
    '',
    'Para obter a versao completa, entre em contato:',
    '  E-mail: thales@thmtecnologia.com',
    '',
    '(c) 2026 THM TECNOLOGIA'
  ) -join [Environment]::NewLine
  Set-Content -Path $nota -Value $msg

  # ============ PASSO 5: MODO APLICATIVO + ICONE ============
  Step 5 'Criando o aplicativo e o icone na Area de Trabalho'

  $appPs1 = @'
# ------------------------------------------------------------
#  (c) 2026 THM TECNOLOGIA. Distribuido sob licenca MIT;
#  Autoria, engenharia e auditoria: THM TECNOLOGIA
#  Pacote oficial de instalacao e distribuicao do
#  MoneyPrinterTurbo (software base sob licenca MIT).
#  a manutencao deste aviso de autoria e obrigatoria.
# ------------------------------------------------------------
# ============================================================
#  MoneyPrinterTurbo - Modo Aplicativo
#  - Inicia o servidor invisivel em segundo plano
#  - Mostra tela de carregamento
#  - Abre a interface em janela propria (estilo aplicativo)
#  - Fica na bandeja do sistema (icone verde perto do relogio)
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:installDir = Join-Path $env:USERPROFILE 'MoneyPrinterTurbo'
$python = Join-Path $script:installDir '.venv\Scripts\python.exe'
$pidFile = Join-Path $script:installDir '.app_server.pid'

function Show-Error([string]$msg) {
  [System.Windows.Forms.MessageBox]::Show($msg, 'MoneyPrinterTurbo', 'OK', 'Error') | Out-Null
}

function Test-PortOpen([int]$p) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $c.Connect('127.0.0.1', $p); $c.Close(); return $true } catch { return $false } finally { $c.Dispose() }
}

function Open-AppWindow([string]$u) {
  $edge1 = "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe"
  $edge2 = "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
  $chrome1 = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
  $chrome2 = "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
  if (Test-Path $edge1) { Start-Process $edge1 -ArgumentList "--app=$u" }
  elseif (Test-Path $edge2) { Start-Process $edge2 -ArgumentList "--app=$u" }
  elseif (Test-Path $chrome1) { Start-Process $chrome1 -ArgumentList "--app=$u" }
  elseif (Test-Path $chrome2) { Start-Process $chrome2 -ArgumentList "--app=$u" }
  else { Start-Process $u }
}

function New-MptIcon {
  $bmp = New-Object System.Drawing.Bitmap 32,32
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'
  $g.Clear([System.Drawing.Color]::FromArgb(255,16,185,129))
  $pts = [System.Drawing.Point[]]@((New-Object System.Drawing.Point 11,7),(New-Object System.Drawing.Point 11,25),(New-Object System.Drawing.Point 26,16))
  $g.FillPolygon([System.Drawing.Brushes]::White, $pts)
  $g.Dispose()
  return [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}

# ---------- Programa instalado? ----------
if (-not (Test-Path $python)) {
  Show-Error ("O MoneyPrinterTurbo nao foi encontrado em " + $script:installDir + ".`n`nExecute primeiro o Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat")
  exit 1
}

# ---------- Ja esta rodando? Entao so abre a janela ----------
if (Test-Path $pidFile) {
  $parts = ((Get-Content $pidFile -First 1) -split ' ')
  $oldPid = 0; $oldPort = 0
  [void][int]::TryParse($parts[0], [ref]$oldPid)
  if ($parts.Count -gt 1) { [void][int]::TryParse($parts[1], [ref]$oldPort) }
  $alive = $null
  if ($oldPid -gt 0) { $alive = Get-Process -Id $oldPid -ErrorAction SilentlyContinue }
  if ($alive -and $oldPort -gt 0 -and (Test-PortOpen $oldPort)) {
    Open-AppWindow ("http://127.0.0.1:" + $oldPort)
    exit 0
  }
  Remove-Item $pidFile -Force
}

# ---------- Escolhe uma porta livre ----------
$script:port = 0
foreach ($p in 8501..8599) { if (-not (Test-PortOpen $p)) { $script:port = $p; break } }
if ($script:port -eq 0) { Show-Error 'Nenhuma porta livre encontrada (8501-8599).'; exit 1 }

# ---------- Tela de carregamento ----------
$splash = New-Object System.Windows.Forms.Form
$splash.FormBorderStyle = 'None'
$splash.StartPosition = 'CenterScreen'
$splash.Size = New-Object System.Drawing.Size(440, 150)
$splash.BackColor = [System.Drawing.Color]::FromArgb(255, 17, 24, 39)
$splash.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = 'Iniciando o MoneyPrinterTurbo...'
$lbl.ForeColor = [System.Drawing.Color]::White
$lbl.Font = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
$lbl.TextAlign = 'MiddleCenter'
$lbl.Dock = 'Top'
$lbl.Height = 64
$sub = New-Object System.Windows.Forms.Label
$sub.Text = 'Preparando o estudio de videos. Isso leva alguns segundos.'
$sub.ForeColor = [System.Drawing.Color]::FromArgb(255, 156, 163, 175)
$sub.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$sub.TextAlign = 'MiddleCenter'
$sub.Dock = 'Top'
$sub.Height = 34
$bar = New-Object System.Windows.Forms.ProgressBar
$bar.Style = 'Marquee'
$bar.MarqueeAnimationSpeed = 25
$bar.Dock = 'Bottom'
$bar.Height = 16
$splash.Controls.Add($sub)
$splash.Controls.Add($lbl)
$splash.Controls.Add($bar)
$splash.Show()
[System.Windows.Forms.Application]::DoEvents()

# ---------- Inicia o servidor invisivel ----------
$env:PYTHONPATH = $script:installDir
$mainPy = Join-Path $script:installDir 'webui\Main.py'
$srvArgs = @('-m','streamlit','run', $mainPy,
  '--server.address=127.0.0.1', ('--server.port=' + $script:port),
  '--browser.gatherUsageStats=False', '--server.headless=True')
$script:server = Start-Process -FilePath $python -ArgumentList $srvArgs -WorkingDirectory $script:installDir -WindowStyle Hidden -PassThru

# ---------- Espera ficar pronto (ate 120 segundos) ----------
$ready = $false
for ($i = 0; $i -lt 240; $i++) {
  Start-Sleep -Milliseconds 500
  [System.Windows.Forms.Application]::DoEvents()
  if ($script:server.HasExited) { break }
  if (Test-PortOpen $script:port) { $ready = $true; break }
}
$splash.Close()

if (-not $ready) {
  if ($script:server -and -not $script:server.HasExited) { & taskkill /PID $script:server.Id /T /F | Out-Null }
  Show-Error ("O servidor nao conseguiu iniciar.`n`nPara ver o motivo, abra a pasta " + $script:installDir + " e execute o webui.bat")
  exit 1
}

Set-Content -Path $pidFile -Value ($script:server.Id.ToString() + ' ' + $script:port.ToString())
$script:url = 'http://127.0.0.1:' + $script:port

# ---------- Abre a interface em janela propria ----------
Open-AppWindow $script:url

# ---------- Icone na bandeja do sistema ----------
$script:tray = New-Object System.Windows.Forms.NotifyIcon
$script:tray.Icon = New-MptIcon
$script:tray.Text = 'MoneyPrinterTurbo - botao direito para opcoes'
$script:tray.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miOpen   = $menu.Items.Add('Abrir o MoneyPrinterTurbo')
$miVideos = $menu.Items.Add('Pasta dos videos prontos')
[void]$menu.Items.Add('-')
$miExit   = $menu.Items.Add('Encerrar o MoneyPrinterTurbo')
$script:tray.ContextMenuStrip = $menu

$miOpen.add_Click({ Open-AppWindow $script:url })
$script:tray.add_DoubleClick({ Open-AppWindow $script:url })
$miVideos.add_Click({
  $tasks = Join-Path $script:installDir 'storage\tasks'
  if (-not (Test-Path $tasks)) { New-Item -ItemType Directory -Path $tasks -Force | Out-Null }
  Start-Process explorer.exe $tasks
})
$miExit.add_Click({
  $script:tray.Visible = $false
  & taskkill /PID $script:server.Id /T /F | Out-Null
  Remove-Item (Join-Path $script:installDir '.app_server.pid') -Force
  [System.Windows.Forms.Application]::Exit()
})

$script:tray.ShowBalloonTip(5000, 'MoneyPrinterTurbo esta rodando',
  'A interface abriu em uma janela propria. Eu fico aqui na bandeja (icone verde, perto do relogio). Botao direito para opcoes.', 'Info')

[System.Windows.Forms.Application]::Run()
'@
  Set-Content -Path (Join-Path $installDir 'MoneyPrinterTurboApp.ps1') -Value $appPs1 -Encoding ASCII

  $appVbs = @'
' ------------------------------------------------------------
'  (c) 2026 THM TECNOLOGIA. Distribuido sob licenca MIT.
'  Autoria, engenharia e auditoria: THM TECNOLOGIA
' ------------------------------------------------------------
' Inicia o MoneyPrinterTurbo em modo aplicativo, sem janela preta.
Set fso = CreateObject("Scripting.FileSystemObject")
appDir = fso.GetParentFolderName(WScript.ScriptFullName)
Set sh = CreateObject("WScript.Shell")
sh.Run "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & appDir & "\MoneyPrinterTurboApp.ps1""", 0, False
'@
  Set-Content -Path (Join-Path $installDir 'MoneyPrinterTurboApp.vbs') -Value $appVbs -Encoding ASCII

  # Icone (play verde)
  $bmp = New-Object System.Drawing.Bitmap 64,64
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'
  $g.Clear([System.Drawing.Color]::FromArgb(255,16,185,129))
  $pts = [System.Drawing.Point[]]@(
    (New-Object System.Drawing.Point 24,16),
    (New-Object System.Drawing.Point 24,48),
    (New-Object System.Drawing.Point 50,32))
  $g.FillPolygon([System.Drawing.Brushes]::White, $pts)
  $g.Dispose()
  $ico = [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
  $fs = [System.IO.File]::Create((Join-Path $installDir 'mpt.ico'))
  $ico.Save($fs); $fs.Close()

  # Atalho na Area de Trabalho (abre sem janela preta)
  $ws = New-Object -ComObject WScript.Shell
  $desktop = [Environment]::GetFolderPath('Desktop')
  $lnk = $ws.CreateShortcut((Join-Path $desktop 'MoneyPrinterTurbo.lnk'))
  $lnk.TargetPath = "$env:WINDIR\System32\wscript.exe"
  $lnk.Arguments = '"' + (Join-Path $installDir 'MoneyPrinterTurboApp.vbs') + '"'
  $lnk.WorkingDirectory = $installDir
  $lnk.IconLocation = (Join-Path $installDir 'mpt.ico')
  $lnk.Description = 'MoneyPrinterTurbo - Gerador de videos com IA'
  $lnk.Save()
  $oldBat = Join-Path $desktop 'MoneyPrinterTurbo.bat'
  if (Test-Path $oldBat) { Remove-Item $oldBat -Force }
  Ok 'Icone verde "MoneyPrinterTurbo" criado na Area de Trabalho.'

  # ============ PASSO 6: ABRIR O APLICATIVO ============
  Step 6 'Abrindo o MoneyPrinterTurbo'
  Info 'Uma tela de carregamento vai aparecer e a interface'
  Info 'abre sozinha em uma janela propria. Ate ja!'
  Start-Process wscript.exe ('"' + (Join-Path $installDir 'MoneyPrinterTurboApp.vbs') + '"')

  Write-Host ''
  Write-Host '  ========================================================' -ForegroundColor Green
  Write-Host '   VERSAO DEMO INSTALADA COM SUCESSO!' -ForegroundColor Green
  Write-Host ''
  Write-Host '   - A interface esta abrindo em uma janela propria' -ForegroundColor White
  Write-Host '   - O icone verde fica na bandeja, perto do relogio' -ForegroundColor White
  Write-Host '   - Para usar de novo: duplo clique no icone verde' -ForegroundColor White
  Write-Host '     "MoneyPrinterTurbo" da sua Area de Trabalho' -ForegroundColor White
  Write-Host ''
  Write-Host '   Versao BR COMPLETA (iPhone, todos os provedores de IA,' -ForegroundColor Yellow
  Write-Host '   suporte THM): thales@thmtecnologia.com' -ForegroundColor Yellow
  Write-Host '  ========================================================' -ForegroundColor Green
}
catch {
  Write-Host ''
  Write-Host '  ========================================================' -ForegroundColor Red
  Write-Host '   ALGO DEU ERRADO:' -ForegroundColor Red
  Write-Host ('   ' + $_.Exception.Message) -ForegroundColor Yellow
  Write-Host ''
  Write-Host '   Rode este instalador de novo - ele continua de onde' -ForegroundColor White
  Write-Host '   parou. Se repetir, fotografe esta tela e peca ajuda.' -ForegroundColor White
  Write-Host '  ========================================================' -ForegroundColor Red
}
