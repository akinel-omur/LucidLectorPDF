<#
 One-shot setup on a fresh Windows machine.
 Usage:  powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
#>
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw 'git is not installed.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw 'Python 3.11+ is not installed.' }

if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

Write-Host "`nRunning tests..." -ForegroundColor Cyan
& .\.venv\Scripts\python.exe -m pytest -q

if (Get-Command node -ErrorAction SilentlyContinue) {
    node web/tests/run-tests.mjs web/tests/sample.pdf
    node web/tests/static-check.mjs
} else {
    Write-Host 'Node.js not found: skipping web tests (optional).' -ForegroundColor Yellow
}

Write-Host "`nDone. Run the app:  .\.venv\Scripts\python.exe main.py" -ForegroundColor Green
Write-Host 'Read AGENTS.md and docs\HANDOFF.md before starting work.'
