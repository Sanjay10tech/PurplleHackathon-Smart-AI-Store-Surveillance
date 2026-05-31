# One-command reviewer setup (Windows PowerShell)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

Write-Host "==> Starting Docker stack"
docker compose up --build -d

Write-Host "==> Checking CCTV videos"
python scripts/setup_videos.py --check
if ($LASTEXITCODE -ne 0) {
    Write-Host "WARN: Copy videos with: python scripts/setup_videos.py --source '<CCTV Footage path>'"
}

Write-Host "==> Installing Python deps"
pip install -e ".[dev,pipeline]" -q

$env:DATABASE_URL = if ($env:DATABASE_URL) { $env:DATABASE_URL } else { "postgresql+asyncpg://si:si@localhost:5432/store_intelligence" }
$env:API_KEY = if ($env:API_KEY) { $env:API_KEY } else { "purple-demo-key" }

Write-Host "==> Running submission validation"
python scripts/validate_submission.py

Write-Host "==> Running test suite"
python -m pytest tests/ --cov=app --cov-branch --cov-fail-under=96 --import-mode=importlib -q

Write-Host "==> Done. Dashboard: http://localhost:8000/dashboard/"
