<# 
Run Angular + Django dev servers in separate PowerShell windows.

Usage:
  .\scripts\run_new_stack.ps1
  .\scripts\run_new_stack.ps1 -InstallDeps

DB_PASSWORD must be supplied via environment/.env or you will be prompted.
#>
param(
  [switch]$InstallDeps,
  [switch]$RunMigrations,
  [switch]$ApplySchema,
  [string]$EnvFile,
  [string]$DbName = "dmis",
  [string]$DbUser = "postgres",
  [SecureString]$DbPassword,
  [string]$DbHost = "localhost",
  [string]$DbPort = "5432"
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendPath = Join-Path $repoRoot "backend"
$frontendPath = Join-Path $repoRoot "frontend"

$installFlagLiteral = if ($InstallDeps) { '$true' } else { '$false' }
$runMigrationsLiteral = if ($RunMigrations) { '$true' } else { '$false' }
$applySchemaLiteral = if ($ApplySchema) { '$true' } else { '$false' }

$dbNameLiteral = if ($DbName) { $DbName } else { "" }
$dbUserLiteral = if ($DbUser) { $DbUser } else { "" }
$dbHostLiteral = if ($DbHost) { $DbHost } else { "localhost" }
$dbPortLiteral = if ($DbPort) { $DbPort } else { "5432" }

$envFilePath = $EnvFile
if (-not $envFilePath) {
  $candidate = Join-Path $backendPath ".env"
  if (Test-Path $candidate) {
    $envFilePath = $candidate
  } else {
    $candidate = Join-Path $repoRoot ".env"
    if (Test-Path $candidate) { $envFilePath = $candidate }
  }
}
$envFileLiteral = if ($envFilePath) { $envFilePath } else { "" }

$envFileHasDbPassword = $false
if ($envFilePath -and (Test-Path $envFilePath)) {
  $envFileHasDbPassword = Select-String -Path $envFilePath -Pattern '^\s*(export\s+)?DB_PASSWORD\s*=' -Quiet
}

if (-not $env:DB_PASSWORD -and -not $DbPassword -and -not $envFileHasDbPassword) {
  $DbPassword = Read-Host "Enter DB_PASSWORD" -AsSecureString
}

$dbPasswordPlain = $null
if (-not $env:DB_PASSWORD -and -not $envFileHasDbPassword -and $DbPassword) {
  $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($DbPassword)
  try {
    $dbPasswordPlain = [System.Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
  } finally {
    [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
  }
}

$backendCmd = @'
$host.ui.RawUI.WindowTitle = "DMIS Django API"
Set-Location -Path "__BACKEND_PATH__"
if (-not (Test-Path ".venv\Scripts\Activate.ps1")) { python -m venv .venv }
. .\.venv\Scripts\Activate.ps1
if ("__ENV_FILE__" -and (Test-Path "__ENV_FILE__")) {
  Get-Content "__ENV_FILE__" | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    if ($line.StartsWith("export ")) { $line = $line.Substring(7).Trim() }
    $parts = $line.Split("=", 2)
    if ($parts.Length -ne 2) { return }
    $key = $parts[0].Trim()
    $val = $parts[1].Trim()
    if ($val.StartsWith('"') -and $val.EndsWith('"')) { $val = $val.Substring(1, $val.Length - 2) }
    elseif ($val.StartsWith("'") -and $val.EndsWith("'")) { $val = $val.Substring(1, $val.Length - 2) }
    if ($key) { [System.Environment]::SetEnvironmentVariable($key, $val) }
  }
  Write-Host "Loaded env file: __ENV_FILE__"
}
if (-not $env:DJANGO_SECRET_KEY) { $env:DJANGO_SECRET_KEY = "dev-only" }
if (-not $env:DJANGO_DEBUG) { $env:DJANGO_DEBUG = "1" }
$env:DJANGO_USE_SQLITE = "0"
if ("__DB_NAME__") { $env:DB_NAME = "__DB_NAME__" }
if ("__DB_USER__") { $env:DB_USER = "__DB_USER__" }
if ("__DB_HOST__") { $env:DB_HOST = "__DB_HOST__" }
if ("__DB_PORT__") { $env:DB_PORT = "__DB_PORT__" }

$missing = @()
foreach ($k in @("DB_NAME","DB_USER","DB_PASSWORD","DB_HOST","DB_PORT")) {
  $value = [System.Environment]::GetEnvironmentVariable($k)
  if ([string]::IsNullOrWhiteSpace($value)) { $missing += $k }
}
if ($missing.Count -gt 0) {
  Write-Host "Missing required DB settings: $($missing -join ', ')"
  Write-Host "Set them in your environment/.env or pass -DbName/-DbUser/-DbHost/-DbPort."
  Pause
  exit 1
}

if (-not $env:DEV_AUTH_ENABLED) { $env:DEV_AUTH_ENABLED = "1" }
if (-not $env:DEV_AUTH_USER_ID) { $env:DEV_AUTH_USER_ID = "dev-user" }
if (-not $env:DEV_AUTH_ROLES) { $env:DEV_AUTH_ROLES = "LOGISTICS" }
if (-not $env:DEV_AUTH_PERMISSIONS) { $env:DEV_AUTH_PERMISSIONS = "replenishment.needs_list.preview,replenishment.needs_list.create_draft" }
if (__INSTALL_FLAG__ -or -not (Test-Path ".venv\Lib\site-packages\django")) { pip install -r requirements.txt }
if (__RUN_MIGRATIONS__) { python manage.py migrate --noinput }
if (__APPLY_SCHEMA__) {
  $psql = Get-Command psql -ErrorAction SilentlyContinue
  if (-not $psql) {
    Write-Host "psql not found in PATH. Install PostgreSQL client tools or add psql to PATH."
    Pause
    exit 1
  }
  $env:PGPASSWORD = $env:DB_PASSWORD
  psql -h $env:DB_HOST -U $env:DB_USER -d $env:DB_NAME -f "EP02_SUPPLY_REPLENISHMENT_SCHEMA.sql"
}
python manage.py runserver 0.0.0.0:8001
'@
$backendCmd = $backendCmd.Replace("__BACKEND_PATH__", $backendPath).
  Replace("__INSTALL_FLAG__", $installFlagLiteral).
  Replace("__RUN_MIGRATIONS__", $runMigrationsLiteral).
  Replace("__APPLY_SCHEMA__", $applySchemaLiteral).
  Replace("__ENV_FILE__", $envFileLiteral).
  Replace("__DB_NAME__", $dbNameLiteral).
  Replace("__DB_USER__", $dbUserLiteral).
  Replace("__DB_HOST__", $dbHostLiteral).
  Replace("__DB_PORT__", $dbPortLiteral)

$frontendCmd = @'
$host.ui.RawUI.WindowTitle = "DMIS Angular UI"
Set-Location -Path "__FRONTEND_PATH__"
if (__INSTALL_FLAG__ -or -not (Test-Path "node_modules")) { npm install }
npm start
'@
$frontendCmd = $frontendCmd.Replace("__FRONTEND_PATH__", $frontendPath).Replace("__INSTALL_FLAG__", $installFlagLiteral)

function Start-EncodedProcess {
  param(
    [string]$Command,
    [string]$DbPasswordPlain
  )
  $bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
  $encoded = [Convert]::ToBase64String($bytes)
  $hadDbPassword = Test-Path Env:DB_PASSWORD
  $originalDbPassword = $env:DB_PASSWORD
  if ($DbPasswordPlain -and -not $hadDbPassword) {
    $env:DB_PASSWORD = $DbPasswordPlain
  }
  try {
    Start-Process -FilePath "powershell" -ArgumentList @("-NoExit", "-EncodedCommand", $encoded) | Out-Null
  } finally {
    if ($DbPasswordPlain -and -not $hadDbPassword) {
      if ($null -eq $originalDbPassword) {
        Remove-Item Env:DB_PASSWORD -ErrorAction SilentlyContinue
      } else {
        $env:DB_PASSWORD = $originalDbPassword
      }
    }
  }
}

Start-EncodedProcess -Command $backendCmd -DbPasswordPlain $dbPasswordPlain
Start-EncodedProcess -Command $frontendCmd

Write-Host "Started Django API (http://localhost:8001) and Angular UI (http://localhost:4200)."
Write-Host "Close each window or press Ctrl+C to stop."
