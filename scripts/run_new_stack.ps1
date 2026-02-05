<# 
Run Angular + Django dev servers in separate PowerShell windows.

Usage:
  .\scripts\run_new_stack.ps1
  .\scripts\run_new_stack.ps1 -InstallDeps
#>
param(
  [switch]$InstallDeps
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendPath = Join-Path $repoRoot "backend"
$frontendPath = Join-Path $repoRoot "frontend"

$installFlagLiteral = if ($InstallDeps) { '$true' } else { '$false' }

$backendCmd = @'
$host.ui.RawUI.WindowTitle = "DMIS Django API"
Set-Location -Path "__BACKEND_PATH__"
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
if (-not $env:DJANGO_SECRET_KEY) { $env:DJANGO_SECRET_KEY = "dev-only" }
if (-not $env:DJANGO_DEBUG) { $env:DJANGO_DEBUG = "1" }
if (-not $env:DJANGO_USE_SQLITE) { $env:DJANGO_USE_SQLITE = "1" }
if (-not $env:DEV_AUTH_ENABLED) { $env:DEV_AUTH_ENABLED = "1" }
if (-not $env:DEV_AUTH_USER_ID) { $env:DEV_AUTH_USER_ID = "dev-user" }
if (-not $env:DEV_AUTH_ROLES) { $env:DEV_AUTH_ROLES = "LOGISTICS" }
if (-not $env:DEV_AUTH_PERMISSIONS) { $env:DEV_AUTH_PERMISSIONS = "replenishment.needs_list.preview,replenishment.needs_list.create_draft" }
if (__INSTALL_FLAG__ -or -not (Test-Path ".venv\Lib\site-packages\django")) { pip install -r requirements.txt }
python manage.py runserver 0.0.0.0:8001
'@
$backendCmd = $backendCmd.Replace("__BACKEND_PATH__", $backendPath).Replace("__INSTALL_FLAG__", $installFlagLiteral)

$frontendCmd = @'
$host.ui.RawUI.WindowTitle = "DMIS Angular UI"
Set-Location -Path "__FRONTEND_PATH__"
if (__INSTALL_FLAG__ -or -not (Test-Path "node_modules")) { npm install }
npm start
'@
$frontendCmd = $frontendCmd.Replace("__FRONTEND_PATH__", $frontendPath).Replace("__INSTALL_FLAG__", $installFlagLiteral)

function Start-EncodedProcess {
  param(
    [string]$Command
  )
  $bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
  $encoded = [Convert]::ToBase64String($bytes)
  Start-Process -FilePath "powershell" -ArgumentList @("-NoExit", "-EncodedCommand", $encoded) | Out-Null
}

Start-EncodedProcess -Command $backendCmd
Start-EncodedProcess -Command $frontendCmd

Write-Host "Started Django API (http://localhost:8001) and Angular UI (http://localhost:4200)."
Write-Host "Close each window or press Ctrl+C to stop."
