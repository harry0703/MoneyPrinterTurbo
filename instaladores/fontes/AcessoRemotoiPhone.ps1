# ------------------------------------------------------------
#  (c) 2026 THM TECNOLOGIA - Todos os direitos reservados.
#  Autoria, engenharia e auditoria: THM TECNOLOGIA
#  Pacote oficial de instalacao e distribuicao do
#  MoneyPrinterTurbo (software base sob licenca MIT).
#  Proibida a redistribuicao sem os devidos creditos.
# ------------------------------------------------------------
# ============================================================
#  MONEYPRINTERTURBO - ACESSO REMOTO PELO IPHONE (Tailscale)
#  - Instala o Tailscale sozinho (rede privada gratuita)
#  - Abre o login no navegador (1 entrada com Google/Apple)
#  - Liga o servidor e mostra QR Codes para o iPhone
#  - Funciona de QUALQUER lugar: 4G, 5G, outra Wi-Fi
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:installDir = Join-Path $env:USERPROFILE 'MoneyPrinterTurbo'
$python = Join-Path $script:installDir '.venv\Scripts\python.exe'
$pidFile = Join-Path $script:installDir '.iphone_server.pid'
$tsExe = Join-Path $env:ProgramFiles 'Tailscale\tailscale.exe'

function Show-Error([string]$msg) {
  [System.Windows.Forms.MessageBox]::Show($msg, 'MoneyPrinterTurbo', 'OK', 'Error') | Out-Null
}

function Test-PortOpen([string]$ip, [int]$p) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $c.Connect($ip, $p); $c.Close(); return $true } catch { return $false } finally { $c.Dispose() }
}

function New-MptIcon {
  $bmp = New-Object System.Drawing.Bitmap 32,32
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = 'AntiAlias'
  $g.Clear([System.Drawing.Color]::FromArgb(255,139,92,246))
  $pts = [System.Drawing.Point[]]@((New-Object System.Drawing.Point 11,7),(New-Object System.Drawing.Point 11,25),(New-Object System.Drawing.Point 26,16))
  $g.FillPolygon([System.Drawing.Brushes]::White, $pts)
  $g.Dispose()
  return [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}

function New-Splash([string]$titulo, [string]$detalhe) {
  $f = New-Object System.Windows.Forms.Form
  $f.FormBorderStyle = 'None'; $f.StartPosition = 'CenterScreen'
  $f.Size = New-Object System.Drawing.Size(480, 150)
  $f.BackColor = [System.Drawing.Color]::FromArgb(255, 17, 24, 39); $f.TopMost = $true
  $l = New-Object System.Windows.Forms.Label
  $l.Text = $titulo; $l.ForeColor = [System.Drawing.Color]::White
  $l.Font = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
  $l.TextAlign = 'MiddleCenter'; $l.Dock = 'Top'; $l.Height = 64
  $s = New-Object System.Windows.Forms.Label
  $s.Text = $detalhe; $s.ForeColor = [System.Drawing.Color]::FromArgb(255, 156, 163, 175)
  $s.Font = New-Object System.Drawing.Font('Segoe UI', 9)
  $s.TextAlign = 'MiddleCenter'; $s.Dock = 'Top'; $s.Height = 34
  $b = New-Object System.Windows.Forms.ProgressBar
  $b.Style = 'Marquee'; $b.MarqueeAnimationSpeed = 25; $b.Dock = 'Bottom'; $b.Height = 16
  $f.Controls.Add($s); $f.Controls.Add($l); $f.Controls.Add($b)
  $f.Show(); [System.Windows.Forms.Application]::DoEvents()
  return $f
}

# ---------- Programa instalado? ----------
if (-not (Test-Path $python)) {
  Show-Error ("O MoneyPrinterTurbo nao foi encontrado.`n`nExecute primeiro o Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat")
  exit 1
}

# ---------- 1. Tailscale instalado? ----------
if (-not (Test-Path $tsExe)) {
  $sp = New-Splash 'Instalando o Tailscale...' 'Rede privada gratuita que conecta seu iPhone ao PC de qualquer lugar.'
  $okInstall = $false
  if (Get-Command winget -ErrorAction SilentlyContinue) {
    & winget install --id tailscale.tailscale -e --accept-source-agreements --accept-package-agreements --silent
    if (Test-Path $tsExe) { $okInstall = $true }
  }
  if (-not $okInstall) {
    $setup = Join-Path $env:TEMP 'tailscale-setup.exe'
    Invoke-WebRequest -Uri 'https://pkgs.tailscale.com/stable/tailscale-setup-latest.exe' -OutFile $setup -UseBasicParsing
    if (Test-Path $setup) {
      Start-Process -FilePath $setup -ArgumentList '/quiet' -Wait
      Remove-Item $setup -Force
    }
    if (Test-Path $tsExe) { $okInstall = $true }
  }
  $sp.Close()
  if (-not $okInstall) {
    Start-Process 'https://tailscale.com/download/windows'
    Show-Error "Nao consegui instalar o Tailscale automaticamente.`n`nAbri a pagina oficial no navegador: instale por la (botao Download) e rode este arquivo de novo."
    exit 1
  }
}

# ---------- 2. Login no Tailscale (1 vez so) ----------
function Get-TsState {
  try { return ((& $tsExe status --json 2>$null | ConvertFrom-Json).BackendState) } catch { return '' }
}
$state = Get-TsState
if ($state -ne 'Running') {
  $sp = New-Splash 'Entrando no Tailscale...' 'Seu navegador vai abrir: entre com sua conta Google, Apple ou Microsoft.'
  Start-Process -FilePath $tsExe -ArgumentList 'up' -WindowStyle Hidden
  $logged = $false
  for ($i = 0; $i -lt 360; $i++) {
    Start-Sleep -Milliseconds 1000
    [System.Windows.Forms.Application]::DoEvents()
    if ((Get-TsState) -eq 'Running') { $logged = $true; break }
  }
  $sp.Close()
  if (-not $logged) {
    Show-Error "O login no Tailscale nao foi concluido.`n`nRode este arquivo de novo e finalize o login na janela do navegador."
    exit 1
  }
}

# ---------- 3. Enderecos da rede privada ----------
$tsIp = (& $tsExe ip -4 2>$null | Select-Object -First 1).Trim()
$tsDns = ''
try {
  $tsDns = ((& $tsExe status --json | ConvertFrom-Json).Self.DNSName).TrimEnd('.')
} catch {}
if (-not $tsIp) { Show-Error 'Nao consegui obter o endereco do Tailscale. Rode o arquivo de novo.'; exit 1 }

# ---------- 4. Firewall (libera para a rede privada) ----------
$rule = Get-NetFirewallRule -DisplayName 'MoneyPrinterTurbo Remoto' -ErrorAction SilentlyContinue
if (-not $rule) {
  $cmd = 'New-NetFirewallRule -DisplayName ''MoneyPrinterTurbo Remoto'' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8501-8599 -Profile Any | Out-Null'
  try { Start-Process powershell -ArgumentList '-NoProfile','-WindowStyle','Hidden','-Command', $cmd -Verb RunAs -Wait } catch {}
}

# ---------- 5. Servidor (reaproveita se ja estiver ligado) ----------
$script:port = 0
if (Test-Path $pidFile) {
  $parts = ((Get-Content $pidFile -First 1) -split ' ')
  $oldPid = 0; $oldPort = 0
  [void][int]::TryParse($parts[0], [ref]$oldPid)
  if ($parts.Count -gt 1) { [void][int]::TryParse($parts[1], [ref]$oldPort) }
  $alive = $null
  if ($oldPid -gt 0) { $alive = Get-Process -Id $oldPid -ErrorAction SilentlyContinue }
  if ($alive -and $oldPort -gt 0 -and (Test-PortOpen '127.0.0.1' $oldPort)) {
    $script:port = $oldPort
    $script:reusing = $true
  } else { Remove-Item $pidFile -Force }
}
if ($script:port -eq 0) {
  foreach ($p in 8511..8599) { if (-not (Test-PortOpen '127.0.0.1' $p)) { $script:port = $p; break } }
  $sp = New-Splash 'Ligando o MoneyPrinterTurbo...' 'Em instantes os QR Codes vao aparecer na tela.'
  $env:PYTHONPATH = $script:installDir
  $mainPy = Join-Path $script:installDir 'webui\Main.py'
  $srvArgs = @('-m','streamlit','run', $mainPy,
    '--server.address=0.0.0.0', ('--server.port=' + $script:port),
    '--browser.gatherUsageStats=False', '--server.headless=True')
  $script:server = Start-Process -FilePath $python -ArgumentList $srvArgs -WorkingDirectory $script:installDir -WindowStyle Hidden -PassThru
  $ready = $false
  for ($i = 0; $i -lt 240; $i++) {
    Start-Sleep -Milliseconds 500
    [System.Windows.Forms.Application]::DoEvents()
    if ($script:server.HasExited) { break }
    if (Test-PortOpen '127.0.0.1' $script:port) { $ready = $true; break }
  }
  $sp.Close()
  if (-not $ready) {
    if ($script:server -and -not $script:server.HasExited) { & taskkill /PID $script:server.Id /T /F | Out-Null }
    Show-Error ("O servidor nao conseguiu iniciar.`n`nAbra a pasta " + $script:installDir + " e execute o webui.bat para ver o motivo.")
    exit 1
  }
  Set-Content -Path $pidFile -Value ($script:server.Id.ToString() + ' ' + $script:port.ToString())
}

# ---------- 6. Pagina com os QR Codes ----------
$script:url = 'http://' + $tsIp + ':' + $script:port
if ($tsDns) { $script:url = 'http://' + $tsDns + ':' + $script:port }
$qrAcesso = [uri]::EscapeDataString($script:url)
$qrApp = [uri]::EscapeDataString('https://apps.apple.com/app/tailscale/id1470499037')
$urlIp = 'http://' + $tsIp + ':' + $script:port

$htmlPath = Join-Path $script:installDir 'acesso-remoto-iphone.html'
$html = @"
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>iPhone em qualquer lugar &bull; MoneyPrinterTurbo</title>
<style>
  body { background:#111827; color:#fff; font-family:'Segoe UI',sans-serif; text-align:center; padding:24px; }
  h1 { color:#8b5cf6; margin-bottom:4px; }
  .sub { color:#9ca3af; margin-top:0; }
  .cards { display:flex; flex-wrap:wrap; justify-content:center; gap:24px; margin:20px 0; }
  .card { background:#1f2937; border-radius:16px; padding:22px; width:330px; }
  .card h2 { color:#10b981; font-size:1.1em; margin-top:0; }
  .qr { background:#fff; display:inline-block; padding:12px; border-radius:12px; }
  .url { font-size:1.1em; font-weight:bold; color:#fbbf24; word-break:break-all; }
  .alt { color:#9ca3af; font-size:.9em; }
  .destaque { color:#f87171; font-weight:bold; }
  ol { text-align:left; color:#d1d5db; padding-left:22px; }
  ol li { margin:8px 0; }
  b { color:#10b981; }
</style>
</head>
<body>
  <h1>&#127760; MoneyPrinterTurbo de QUALQUER lugar</h1>
  <p class="sub">4G, 5G, trabalho, viagem &mdash; o iPhone conecta direto neste PC, com seguran&ccedil;a.</p>
  <div class="cards">
    <div class="card">
      <h2>PASSO 1 &mdash; S&Oacute; NA PRIMEIRA VEZ</h2>
      <div class="qr"><img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=$qrApp" width="200" height="200" alt="QR App Store"></div>
      <ol>
        <li>Aponte a c&acirc;mera do iPhone para este QR: abre o <b>Tailscale na App Store</b>. Instale.</li>
        <li>Abra o app e entre com a <span class="destaque">MESMA conta</span> (Google/Apple/Microsoft) que voc&ecirc; acabou de usar no PC.</li>
        <li>Deixe a chavinha do Tailscale <b>ligada</b> (Connected).</li>
      </ol>
    </div>
    <div class="card">
      <h2>PASSO 2 &mdash; ACESSAR O PROGRAMA</h2>
      <div class="qr"><img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=$qrAcesso" width="200" height="200" alt="QR Acesso"></div>
      <ol>
        <li>Aponte a c&acirc;mera para este QR: a interface abre no Safari.</li>
        <li>Toque em <b>Compartilhar &rarr; "Adicionar &agrave; Tela de In&iacute;cio"</b> para virar aplicativo.</li>
        <li>Funciona em casa, na rua, em qualquer rede!</li>
      </ol>
    </div>
  </div>
  <p>Endere&ccedil;o (se preferir digitar):</p>
  <p class="url">$($script:url)</p>
  <p class="alt">Alternativa: $urlIp</p>
  <p class="alt">Este PC precisa estar <b>ligado e com o Tailscale ativo</b> para o iPhone acessar.<br>
  O &iacute;cone roxo na bandeja (perto do rel&oacute;gio) tem as op&ccedil;&otilde;es.</p>
</body>
</html>
"@
Set-Content -Path $htmlPath -Value $html -Encoding UTF8
Start-Process $htmlPath

# ---------- 7. Bandeja ----------
if ($script:reusing) { exit 0 }

$script:tray = New-Object System.Windows.Forms.NotifyIcon
$script:tray.Icon = New-MptIcon
$script:tray.Text = 'MoneyPrinterTurbo (remoto) - botao direito para opcoes'
$script:tray.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miQr     = $menu.Items.Add('Mostrar QR Codes de acesso')
$miLocal  = $menu.Items.Add('Abrir tambem neste computador')
$miVideos = $menu.Items.Add('Pasta dos videos prontos')
[void]$menu.Items.Add('-')
$miExit   = $menu.Items.Add('Encerrar o servidor')
$script:tray.ContextMenuStrip = $menu

$script:htmlPath = $htmlPath
$miQr.add_Click({ Start-Process $script:htmlPath })
$script:tray.add_DoubleClick({ Start-Process $script:htmlPath })
$miLocal.add_Click({ Start-Process ('http://127.0.0.1:' + $script:port) })
$miVideos.add_Click({
  $tasks = Join-Path $script:installDir 'storage\tasks'
  if (-not (Test-Path $tasks)) { New-Item -ItemType Directory -Path $tasks -Force | Out-Null }
  Start-Process explorer.exe $tasks
})
$miExit.add_Click({
  $script:tray.Visible = $false
  & taskkill /PID $script:server.Id /T /F | Out-Null
  Remove-Item (Join-Path $script:installDir '.iphone_server.pid') -Force
  [System.Windows.Forms.Application]::Exit()
})

$script:tray.ShowBalloonTip(6000, 'Acesso remoto pronto!',
  'Siga os 2 passos da pagina que abriu. Depois do primeiro uso, e so abrir o icone no iPhone - de qualquer lugar.', 'Info')

[System.Windows.Forms.Application]::Run()
