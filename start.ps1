# Stellaris Save Editor - Cross-Platform Startup Script
# Usage: .\start.ps1

$ErrorActionPreference = "Stop"

Write-Host "================================" -ForegroundColor Cyan
Write-Host "  Stellaris Save Editor - Starting..." -ForegroundColor Cyan
Write-Host "================================" -ForegroundColor Cyan

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check Python
Write-Host "[1/4] Checking Python..." -ForegroundColor Yellow
try {
    $pythonVer = & python3 --version 2>&1
    if ($LASTEXITCODE -ne 0) { throw }
    Write-Host "  OK: $pythonVer" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: python3 not found. Install Python 3.10+ or use uv." -ForegroundColor Red
    Write-Host "  Tip: pip install uv && uv python install 3.12" -ForegroundColor Gray
    exit 1
}

# Check/Install Python deps
Write-Host "[2/4] Checking Python dependencies..." -ForegroundColor Yellow
$pyDeps = @('no requirements file')
if (Test-Path "$ProjectRoot\mini-services\save-parser\requirements.txt") {
    $pyDeps = Get-Content "$ProjectRoot\mini-services\save-parser\requirements.txt"
}
# No external deps needed for the parser (stdlib only)
Write-Host "  OK: No external Python dependencies required" -ForegroundColor Green

# Install Node.js deps
Write-Host "[3/4] Installing Node.js dependencies..." -ForegroundColor Yellow
Push-Location $ProjectRoot
try {
    if (Get-Command pnpm -ErrorAction SilentlyContinue) {
        & pnpm install --frozen-lockfile 2>&1 | Out-Null
        Write-Host "  OK: pnpm install completed" -ForegroundColor Green
    } elseif (Get-Command bun -ErrorAction SilentlyContinue) {
        & bun install --frozen-lockfile 2>&1 | Out-Null
        Write-Host "  OK: bun install completed" -ForegroundColor Green
    } else {
        & npm install 2>&1 | Out-Null
        Write-Host "  OK: npm install completed" -ForegroundColor Green
    }
} catch {
    Write-Host "  ERROR: Failed to install dependencies" -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

# Start services
Write-Host "[4/4] Starting services..." -ForegroundColor Yellow

# Kill existing Python service on port 3001
$port3001 = Get-NetTCPConnection -LocalPort 3001 -ErrorAction SilentlyContinue
if ($port3001) {
    $port3001 | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Write-Host "  Stopped existing Python service on :3001" -ForegroundColor Gray
}

# Start Python save parser service
Write-Host "  Starting Python save parser on :3001..." -ForegroundColor Gray
$pyProcess = Start-Process -FilePath "python3" `
    -ArgumentList "$ProjectRoot\mini-services\save-parser\server.py" `
    -WorkingDirectory "$ProjectRoot\mini-services\save-parser" `
    -Environment @{ PORT = "3001" } `
    -WindowStyle Hidden -PassThru
Write-Host "  Python service started (PID: $($pyProcess.Id))" -ForegroundColor Green

Start-Sleep -Seconds 2

# Check if service is running
try {
    $response = Invoke-WebRequest -Uri "http://localhost:3001/api/status" -TimeoutSec 3 -UseBasicParsing
    Write-Host "  Python service verified on :3001" -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Python service may not have started. Check logs." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "================================" -ForegroundColor Green
Write-Host "  All services started!" -ForegroundColor Green
Write-Host "================================" -ForegroundColor Green
Write-Host ""
Write-Host "Next.js dev server should be running at:" -ForegroundColor Cyan
Write-Host "  Local:   http://localhost:3000" -ForegroundColor White
Write-Host ""
Write-Host "Press Ctrl+C to stop all services." -ForegroundColor Yellow
Write-Host ""

# Cleanup on exit
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
    Write-Host "`nShutting down..." -ForegroundColor Yellow
    if ($pyProcess -and !$pyProcess.HasExited) {
        Stop-Process -Id $pyProcess.Id -Force -ErrorAction SilentlyContinue
        Write-Host "  Python service stopped" -ForegroundColor Gray
    }
}

# Keep script running
try {
    Wait-Process -Id $pyProcess.Id
} catch {
    # Script was terminated
}
