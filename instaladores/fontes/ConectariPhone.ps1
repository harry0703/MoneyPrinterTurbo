# ------------------------------------------------------------
#  (c) 2026 THM TECNOLOGIA - Todos os direitos reservados.
#  Autoria, engenharia e auditoria: THM TECNOLOGIA
#  Pacote oficial de instalacao e distribuicao do
#  MoneyPrinterTurbo (software base sob licenca MIT).
#  Proibida a redistribuicao sem os devidos creditos.
# ------------------------------------------------------------
# ============================================================
#  MONEYPRINTERTURBO - CONEXAO COM IPHONE (fluxo unico)
#  - Autoriza o firewall sozinho (1 clique no aviso do Windows)
#  - Liga o servidor acessivel pelo celular (invisivel)
#  - Mostra um QR CODE na tela: aponte a camera do iPhone
#  - Fica na bandeja do sistema com menu de opcoes
# ============================================================
$ErrorActionPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$script:installDir = Join-Path $env:USERPROFILE 'MoneyPrinterTurbo'
$python = Join-Path $script:installDir '.venv\Scripts\python.exe'
$pidFile = Join-Path $script:installDir '.iphone_server.pid'

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
  $g.Clear([System.Drawing.Color]::FromArgb(255,59,130,246))
  $pts = [System.Drawing.Point[]]@((New-Object System.Drawing.Point 11,7),(New-Object System.Drawing.Point 11,25),(New-Object System.Drawing.Point 26,16))
  $g.FillPolygon([System.Drawing.Brushes]::White, $pts)
  $g.Dispose()
  return [System.Drawing.Icon]::FromHandle($bmp.GetHicon())
}

# ---------- Programa instalado? ----------
if (-not (Test-Path $python)) {
  Show-Error ("O MoneyPrinterTurbo nao foi encontrado.`n`nExecute primeiro o Instalar-MoneyPrinterTurbo-TUDO-EM-UM.bat")
  exit 1
}

# ---------- Autoriza o firewall (1 clique no aviso) ----------
$rule = Get-NetFirewallRule -DisplayName 'MoneyPrinterTurbo' -ErrorAction SilentlyContinue
if (-not $rule) {
  $cmd = 'New-NetFirewallRule -DisplayName ''MoneyPrinterTurbo'' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8501-8599 -Profile Private,Domain | Out-Null'
  try {
    Start-Process powershell -ArgumentList '-NoProfile','-WindowStyle','Hidden','-Command', $cmd -Verb RunAs -Wait
  } catch {}
}

# ---------- Ja esta rodando? So reabre o QR ----------
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

# ---------- Splash ----------
$splash = $null
if ($script:port -eq 0) {
  foreach ($p in 8511..8599) { if (-not (Test-PortOpen '127.0.0.1' $p)) { $script:port = $p; break } }
  $splash = New-Object System.Windows.Forms.Form
  $splash.FormBorderStyle = 'None'
  $splash.StartPosition = 'CenterScreen'
  $splash.Size = New-Object System.Drawing.Size(460, 150)
  $splash.BackColor = [System.Drawing.Color]::FromArgb(255, 17, 24, 39)
  $splash.TopMost = $true
  $lbl = New-Object System.Windows.Forms.Label
  $lbl.Text = 'Preparando a conexao com o iPhone...'
  $lbl.ForeColor = [System.Drawing.Color]::White
  $lbl.Font = New-Object System.Drawing.Font('Segoe UI', 13, [System.Drawing.FontStyle]::Bold)
  $lbl.TextAlign = 'MiddleCenter'; $lbl.Dock = 'Top'; $lbl.Height = 64
  $sub = New-Object System.Windows.Forms.Label
  $sub.Text = 'Em instantes um QR Code vai aparecer na tela.'
  $sub.ForeColor = [System.Drawing.Color]::FromArgb(255, 156, 163, 175)
  $sub.Font = New-Object System.Drawing.Font('Segoe UI', 9)
  $sub.TextAlign = 'MiddleCenter'; $sub.Dock = 'Top'; $sub.Height = 34
  $bar = New-Object System.Windows.Forms.ProgressBar
  $bar.Style = 'Marquee'; $bar.MarqueeAnimationSpeed = 25; $bar.Dock = 'Bottom'; $bar.Height = 16
  $splash.Controls.Add($sub); $splash.Controls.Add($lbl); $splash.Controls.Add($bar)
  $splash.Show()
  [System.Windows.Forms.Application]::DoEvents()

  # ---------- Inicia o servidor visivel para a rede ----------
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
  $splash.Close()
  if (-not $ready) {
    if ($script:server -and -not $script:server.HasExited) { & taskkill /PID $script:server.Id /T /F | Out-Null }
    Show-Error ("O servidor nao conseguiu iniciar.`n`nAbra a pasta " + $script:installDir + " e execute o webui.bat para ver o motivo.")
    exit 1
  }
  Set-Content -Path $pidFile -Value ($script:server.Id.ToString() + ' ' + $script:port.ToString())
}

# ---------- Descobre os enderecos ----------
$ips = @(Get-NetIPAddress -AddressFamily IPv4 |
  Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
  Sort-Object -Property InterfaceMetric |
  Select-Object -ExpandProperty IPAddress)
if (-not $ips -or $ips.Count -eq 0) {
  Show-Error 'Nenhuma conexao de rede encontrada. Conecte o PC ao Wi-Fi ou cabo e tente de novo.'
  exit 1
}
$mainIp = $ips[0]
$script:url = 'http://' + $mainIp + ':' + $script:port
$hostUrl = 'http://' + ($env:COMPUTERNAME.ToLower()) + '.local:' + $script:port
$qrData = [uri]::EscapeDataString($script:url)

# ---------- Gera a pagina com o QR Code ----------
$htmlPath = Join-Path $script:installDir 'conectar-iphone.html'
$html = @"
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Conectar o iPhone &bull; MoneyPrinterTurbo</title>
<style>
  body { background:#111827; color:#fff; font-family:'Segoe UI',sans-serif; text-align:center; padding:24px; }
  h1 { color:#10b981; margin-bottom:4px; }
  .sub { color:#9ca3af; margin-top:0; }
  .qr { background:#fff; display:inline-block; padding:18px; border-radius:16px; margin:18px; }
  .url { font-size:1.5em; font-weight:bold; color:#fbbf24; letter-spacing:1px; }
  .alt { color:#9ca3af; font-size:.95em; }
  .steps { max-width:520px; margin:18px auto; text-align:left; background:#1f2937; border-radius:12px; padding:18px 26px; }
  .steps li { margin:12px 0; font-size:1.08em; }
  b { color:#10b981; }
</style>
</head>
<body>
  <h1>&#9654; MoneyPrinterTurbo no iPhone</h1>
  <p class="sub">O servidor j&aacute; est&aacute; ligado neste computador. Agora &eacute; s&oacute; conectar o celular:</p>
  <div class="qr"><img src="https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=$qrData" width="280" height="280" alt="QR Code"></div>
  <ol class="steps">
    <li><b>1.</b> Conecte o iPhone na <b>mesma rede Wi-Fi</b> deste computador.</li>
    <li><b>2.</b> Abra a <b>C&acirc;mera</b> do iPhone e aponte para o QR Code acima. Toque no aviso amarelo que aparecer.</li>
    <li><b>3.</b> Quando a p&aacute;gina abrir no Safari, toque em <b>Compartilhar</b> (quadrado com seta) e depois em <b>"Adicionar &agrave; Tela de In&iacute;cio"</b>. Pronto: vira um aplicativo no seu iPhone!</li>
  </ol>
  <p>Se preferir digitar, o endere&ccedil;o &eacute;:</p>
  <p class="url">$($script:url)</p>
  <p class="alt">Alternativa: $hostUrl</p>
  <p class="alt">Mantenha este computador ligado enquanto usa no iPhone.<br>
  O &iacute;cone azul na bandeja (perto do rel&oacute;gio) tem as op&ccedil;&otilde;es &mdash; inclusive Encerrar.</p>
</body>
</html>
"@
Set-Content -Path $htmlPath -Value $html -Encoding UTF8
Start-Process $htmlPath

# ---------- Bandeja do sistema ----------
if ($script:reusing) { exit 0 }

$script:tray = New-Object System.Windows.Forms.NotifyIcon
$script:tray.Icon = New-MptIcon
$script:tray.Text = 'MoneyPrinterTurbo (iPhone) - botao direito para opcoes'
$script:tray.Visible = $true

$menu = New-Object System.Windows.Forms.ContextMenuStrip
$miQr     = $menu.Items.Add('Mostrar QR Code de conexao')
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

$script:tray.ShowBalloonTip(6000, 'Pronto para o iPhone!',
  'Aponte a camera do iPhone para o QR Code que abriu na tela. Eu fico aqui na bandeja (icone azul).', 'Info')

[System.Windows.Forms.Application]::Run()
