<#
 Save work to GitHub so another account / AI session can continue.
 Pulls (rebase), runs fast tests, commits everything, pushes.

 Usage:  scripts\sync.ps1 "feat: short message"
         scripts\sync.ps1            # default message "chore: sync"
#>
param([string]$Message = 'chore: sync')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)

$branch = (git rev-parse --abbrev-ref HEAD).Trim()
Write-Host "Branch: $branch" -ForegroundColor Cyan

# Fast safety net: pure-logic tests only.
if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m pytest -q 2>$null
    if ($LASTEXITCODE -ne 0) {
        $a = Read-Host 'Tests failed or pytest missing. Push anyway? (y/N)'
        if ($a -ne 'y') { exit 1 }
    }
}

# Refuse to commit secrets or binaries by accident.
$bad = git status --porcelain | Select-String -Pattern '\.(exe|env|pem|key)$|secrets?\.' 
if ($bad) { Write-Host "Suspicious files:`n$bad" -ForegroundColor Red; exit 1 }

git add -A
if (git status --porcelain) { git commit -m $Message } else { Write-Host 'Nothing to commit.' }

git pull --rebase origin $branch
git push -u origin $branch
Write-Host "`nPushed. Remote: $(git remote get-url origin)" -ForegroundColor Green
