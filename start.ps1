# Day-to-day launcher: activate the venv and start the server.
# Usage:  .\start.ps1

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

if (-not (Test-Path "$root\.venv\Scripts\Activate.ps1")) {
    Write-Error "No .venv found. Run setup first: python -m venv .venv; .venv\Scripts\Activate.ps1; pip install -r requirements.txt"
    exit 1
}

if (-not (Get-Process "ollama*" -ErrorAction SilentlyContinue)) {
    Write-Warning "Ollama doesn't look like it's running. Start it (or just open the Ollama app) before asking questions."
}

& "$root\.venv\Scripts\Activate.ps1"
Write-Host "Starting Personal RAG at http://localhost:8000 (Ctrl+C to stop)" -ForegroundColor Cyan
uvicorn app.main:app --host 127.0.0.1 --port 8000
