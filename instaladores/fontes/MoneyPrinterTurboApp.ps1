# ------------------------------------------------------------
#  (c) 2026 THM TECNOLOGIA - Todos os direitos reservados.
#  Autoria, engenharia e auditoria: THM TECNOLOGIA
#  Pacote oficial de instalacao e distribuicao do
#  MoneyPrinterTurbo (software base sob licenca MIT).
#  Proibida a redistribuicao sem os devidos creditos.
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
  Show-Error ("O MoneyPrinterTurbo nao foi encontrado em " + $script:installDir + ".`n`nExecute primeiro o instalar-moneyprinterturbo.bat")
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
