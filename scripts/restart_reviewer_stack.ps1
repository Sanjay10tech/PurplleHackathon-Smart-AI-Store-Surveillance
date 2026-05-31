# Restart Store Intelligence when localhost:8000 hangs on load
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> Stopping stack..."
docker compose down 2>$null

Write-Host "==> Waiting for port 8000 to clear..."
Start-Sleep -Seconds 3

Write-Host "==> Starting stack (API responds before data bootstrap finishes)..."
docker compose up --build -d

Write-Host "==> Waiting for /health..."
$ok = $false
for ($i = 1; $i -le 30; $i++) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 5 -UseBasicParsing
        if ($r.StatusCode -eq 200) {
            $ok = $true
            break
        }
    } catch {
        Start-Sleep -Seconds 2
    }
}

if ($ok) {
    Write-Host "OK  http://localhost:8000/health"
    Write-Host "    http://localhost:8000/dashboard/"
    Write-Host "    http://localhost:8000/docs"
    Write-Host "    http://localhost:8000/reviewer/api"
} else {
    Write-Host "FAIL — Docker may be stuck. Restart Docker Desktop, then run this script again."
    exit 1
}
