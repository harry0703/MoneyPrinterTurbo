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
  Write-Host '     MONEYPRINTERTURBO - INSTALACAO COMPLETA' -ForegroundColor Green
  Write-Host '     Gerador de videos com IA - tudo em um unico fluxo' -ForegroundColor Green
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

  # ============ PASSO 4: SUAS CHAVES ============
  Step 4 'Configurando suas chaves (janelas vao abrir)'
  $cfg = Join-Path $installDir 'config.toml'
  if (-not (Test-Path $cfg)) {
    Copy-Item (Join-Path $installDir 'config.example.toml') $cfg
  }
  $cfgText = Get-Content -Raw $cfg
  $needPexels = $cfgText.Contains('pexels_api_keys = []')
  $needLlm = $cfgText.Contains('llm_provider = "openai"') -and $cfgText.Contains('openai_api_key = ""')
  if ($needPexels -or $needLlm) {
    Info 'Abrindo a pagina do Pexels no navegador (chave gratuita de videos)...'
    if ($needPexels) { Start-Process 'https://www.pexels.com/api/' }
    $pexels = ''
    if ($needPexels) { $pexels = [Microsoft.VisualBasic.Interaction]::InputBox(
      "1 de 2 - CHAVE DO PEXELS (videos de fundo, gratuita)`n`nA pagina do Pexels abriu no seu navegador.`nCrie a conta (ou entre), copie sua API Key e cole aqui embaixo.`n`nSe quiser fazer isso depois, deixe em branco e clique OK.",
      'MoneyPrinterTurbo - Chave do Pexels', '') }
    if ($pexels.Trim()) {
      (Get-Content -Raw $cfg) -replace [regex]::Escape('pexels_api_keys = []'), ('pexels_api_keys = ["' + $pexels.Trim() + '"]') | Set-Content $cfg
      Ok 'Chave do Pexels salva.'
    } elseif ($needPexels) { Info 'Pexels deixado para depois (rode o instalador de novo para preencher).' }
    $llm = ''
    if ($needLlm) { $llm = [Microsoft.VisualBasic.Interaction]::InputBox(
      "2 de 2 - CHAVE DO LLM (escreve os roteiros)`n`nSe voce tem uma chave da OpenAI, cole aqui.`n`nSe NAO tem, deixe em branco e clique OK:`nsera usado o Pollinations, que e gratuito e nao precisa de chave.",
      'MoneyPrinterTurbo - Chave do LLM (opcional)', '') }
    if ($llm.Trim()) {
      (Get-Content -Raw $cfg) -replace [regex]::Escape('openai_api_key = ""'), ('openai_api_key = "' + $llm.Trim() + '"') | Set-Content $cfg
      Ok 'Chave OpenAI salva.'
    } elseif ($needLlm) {
      (Get-Content -Raw $cfg) -replace [regex]::Escape('llm_provider = "openai"'), 'llm_provider = "pollinations"' | Set-Content $cfg
      Ok 'Configurado o modo gratuito (Pollinations).'
    }
  } else {
    Ok 'Chaves ja preenchidas anteriormente. Mantendo.'
  }

  # ============ PASSO 5: MODO APLICATIVO + ICONE ============
  Step 5 'Criando o aplicativo e o icone na Area de Trabalho'

  $appPs1 = @'
__APP_PS1__
'@
  Set-Content -Path (Join-Path $installDir 'MoneyPrinterTurboApp.ps1') -Value $appPs1 -Encoding ASCII

  $appVbs = @'
__APP_VBS__
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
  Write-Host '   INSTALACAO 100% CONCLUIDA!' -ForegroundColor Green
  Write-Host ''
  Write-Host '   - A interface esta abrindo em uma janela propria' -ForegroundColor White
  Write-Host '   - O icone verde fica na bandeja, perto do relogio' -ForegroundColor White
  Write-Host '   - Para usar de novo: duplo clique no icone verde' -ForegroundColor White
  Write-Host '     "MoneyPrinterTurbo" da sua Area de Trabalho' -ForegroundColor White
  Write-Host ''
  Write-Host '   Dica: na interface, troque o idioma para Portugues' -ForegroundColor White
  Write-Host '   e escolha a voz pt-BR-FranciscaNeural.' -ForegroundColor White
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
