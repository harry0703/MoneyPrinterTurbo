Write-Host "========================================="
Write-Host "MoneyPrinterTurboCN Docker Start Script"
Write-Host "========================================="
Write-Host ""

# Parse command line arguments
$useGpu = $true
Write-Host "[INFO] Command line arguments:"
if ($args.Count -gt 0) {
    $arg = $args[0]
    if ($arg -eq "--cpu") {
        Write-Host "[INFO] --cpu flag detected, will use CPU-only configuration"
        $useGpu = $false
    } elseif ($arg -eq "--gpu") {
        Write-Host "[INFO] --gpu flag detected, will use GPU-accelerated configuration"
        $useGpu = $true
    } else {
        Write-Host "[ERROR] Unknown argument: $arg"
        Write-Host "Usage: start-docker.ps1 [--cpu | --gpu]"
        Write-Host "  --cpu   : Use CPU-only configuration"
        Write-Host "  --gpu   : Use GPU-accelerated configuration (default)"
        Write-Host "  no args : Use GPU-accelerated configuration (default)"
        Read-Host "Press Enter to continue..."
        exit 1
    }
} else {
    Write-Host "[INFO] No arguments specified, will use GPU-accelerated configuration (default)"
}
Write-Host ""

# Check Docker installation and daemon
Write-Host "[INFO] Checking Docker installation and daemon..."
Write-Host "[INFO] This may take a few seconds..."
$dockerStatus = docker version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Docker is not installed or daemon is not running"
    Write-Host "[DEBUG] Docker error: $dockerStatus"
    Write-Host ""
    Write-Host "Possible reasons:"
    Write-Host "1. Docker is not installed"
    Write-Host "2. Docker Desktop is not running"
    Write-Host "3. Docker Desktop is still starting up"
    Write-Host "4. Docker Desktop encountered an error"
    Write-Host "5. Docker client and server API version mismatch"
    Write-Host ""
    Write-Host "Steps to resolve:"
    Write-Host "1. Check if Docker Desktop is installed"
    Write-Host "2. Open Docker Desktop application"
    Write-Host "3. Wait for it to fully start (check system tray icon)"
    Write-Host "4. If already running, try restarting Docker Desktop:"
    Write-Host "   - Right-click Docker icon in system tray"
    Write-Host "   - Select 'Quit Docker Desktop'"
    Write-Host "   - Wait 10 seconds, then restart Docker Desktop"
    Write-Host "   - Wait 30-60 seconds for it to fully initialize"
    Write-Host "5. If still failing, check Docker Desktop logs:"
    Write-Host "   - Open Docker Desktop"
    Write-Host "   - Click on bug icon in top-right corner"
    Write-Host "   - Select 'Logs' to view detailed error messages"
    Write-Host ""
    Read-Host "Press Enter to continue..."
    exit 1
} else {
    Write-Host "[INFO] Docker is installed and daemon is running"
    Write-Host ""
}

# Check whisper model directory
Write-Host "[INFO] Checking whisper model directory..."
if (!(Test-Path "models")) {
    Write-Host "[INFO] Creating models directory..."
    New-Item -ItemType Directory -Path "models" -Force | Out-Null
}
Write-Host "[INFO] Whisper models will be stored in: $((Get-Location).Path)\models"
Write-Host ""

# Check config.toml
Write-Host "[INFO] Checking configuration file..."
if (!(Test-Path "config.toml")) {
    Write-Host "[WARNING] config.toml not found"
    Write-Host "[INFO] Application will use default configuration"
    Write-Host "[INFO] You can copy config.example.toml to config.toml and customize it"
} else {
    Write-Host "[INFO] Configuration file found: $((Get-Location).Path)\config.toml"
}
Write-Host ""

Write-Host "=== Starting Docker Containers ==="
Write-Host ""

# Stop any existing containers with same name
Write-Host "[INFO] Stopping existing containers..."
# Remove all containers with moneyprinterturbocn in their name
$containers = docker ps -a --format "{{.Names}}" | Select-String "moneyprinterturbocn"
foreach ($container in $containers) {
    $containerName = $container.ToString().Trim()
    Write-Host "[INFO] Stopping container: $containerName"
    docker stop $containerName 2>$null
    Write-Host "[INFO] Removing container: $containerName"
    docker rm $containerName 2>$null
}
Write-Host "[INFO] Existing containers cleaned up"
Write-Host ""

# Start containers using docker-compose
Write-Host "[INFO] Starting containers..."
if ($useGpu) {
    Write-Host "[INFO] Using GPU configuration (docker-compose.yml)"
    docker-compose up -d
} else {
    Write-Host "[INFO] Using CPU configuration (docker-compose.cpu.yml)"
    docker-compose -f docker-compose.cpu.yml up -d
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to start containers"
    Write-Host "[INFO] Please check Docker Desktop for more details"
    Read-Host "Press Enter to continue..."
    exit 1
}

# Give containers time to start
Write-Host "[INFO] Giving containers time to start..."
Start-Sleep -Seconds 3

# Check if containers are running
Write-Host ""
Write-Host "[INFO] Checking container status..."
docker ps --filter name=moneyprinterturbocn-webui --filter name=moneyprinterturbocn-api --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

$webuiContainer = docker ps --filter name=moneyprinterturbocn-webui
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "========================================="
    Write-Host "[SUCCESS] Containers started successfully!"
    Write-Host "========================================="
    Write-Host ""
    Write-Host "=== Access Information ==="
    Write-Host "WebUI:        http://localhost:8501"
    Write-Host "API:          http://localhost:8080"
    Write-Host "API Docs:     http://localhost:8080/docs"
    Write-Host ""
    Write-Host "=== Volume Mounts ==="
    Write-Host "Project:      $((Get-Location).Path):/MoneyPrinterTurboCN"
    Write-Host "Models:       $((Get-Location).Path)\models:/MoneyPrinterTurboCN/models"
    Write-Host "Config:       $((Get-Location).Path)\config.toml:/MoneyPrinterTurboCN/config.toml"
    Write-Host "Storage:      $((Get-Location).Path)\storage:/MoneyPrinterTurboCN/storage"
    Write-Host ""
    Write-Host "=== GPU Support ==="
    if ($useGpu) {
        Write-Host "Status:       GPU mode enabled"
        Write-Host "Note:         This image includes CUDA 11.8 runtime"
        Write-Host "               The application will use GPU acceleration"
        Write-Host ""
        Write-Host "[TIP] If you don't have GPU or want to use CPU mode,"
        Write-Host "[TIP] run: .\start-docker.ps1 --cpu"
    } else {
        Write-Host "Status:       CPU mode"
        Write-Host "Note:         Running in CPU-only mode"
        Write-Host ""
        Write-Host "[TIP] If you have GPU and want to use GPU acceleration,"
        Write-Host "[TIP] run: .\start-docker.ps1 --gpu"
    }
    Write-Host ""
    Write-Host "=== Whisper Models ==="
    Write-Host "Location:     $((Get-Location).Path)\models"
    Write-Host "Note:         Whisper models will be downloaded automatically on first use"
    Write-Host "               or you can manually place models in this directory"
    Write-Host ""
    Write-Host "=== Useful Commands ==="
    Write-Host "View logs:    docker-compose logs -f"
    Write-Host "Stop:         docker-compose down"
    Write-Host "Restart:      docker-compose restart"
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[ERROR] Failed to start containers"
    Write-Host "[INFO] Please check Docker Desktop for more details"
    Write-Host ""
    Write-Host "Troubleshooting:"
    Write-Host "1. Check if ports 8501 and 8080 are available"
    Write-Host "2. Check Docker Desktop logs"
    Write-Host "3. Try running: docker-compose up (without -d) to see detailed errors"
    Read-Host "Press Enter to continue..."
    exit 1
}

Write-Host "=== Start Complete ==="
Read-Host "Press Enter to exit..."
