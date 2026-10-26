# Rotate the PostgreSQL password used by the ERP and update <root>\.env in one shot.
# Pure ASCII on purpose: PowerShell 5.1 reads .ps1 as ANSI.
#
# Usage (from the project root):
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\rotate_db_password.ps1 -DryRun
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\rotate_db_password.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ops\rotate_db_password.ps1 -NewPassword 'YourPass123'
#
# What it does:
#   1. ALTER ROLE <user> WITH PASSWORD '<new>'  (a role may change its own password)
#   2. rewrites the password segment of DATABASE_URL in .env (UTF-8, no BOM)
#   3. reconnects with the new password to prove it works
#
# After running: restart the ERP backend, it reads .env only at startup.

[CmdletBinding()]
param(
    [string]$NewPassword = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'

# --- resolve project root (walk up until .env is found) ---
$Root = $PSScriptRoot
while ($Root -and -not (Test-Path -LiteralPath (Join-Path $Root '.env'))) {
    $Root = Split-Path -Parent $Root
}
if (-not $Root) { Write-Error '.env not found'; exit 1 }
$EnvFile = Join-Path $Root '.env'

# --- parse DATABASE_URL ---
$text = Get-Content -LiteralPath $EnvFile -Raw
if ($text -notmatch '(?m)^\s*DATABASE_URL\s*=\s*(\S+)\s*$') {
    Write-Error 'DATABASE_URL missing in .env'
    exit 1
}
$dsn = $Matches[1]
if ($dsn -notmatch '^(?<scheme>[^:]+)://(?<user>[^:]+):(?<pass>[^@]+)@(?<host>[^:/]+):(?<port>\d+)/(?<db>[^?]+)') {
    Write-Error 'Cannot parse DATABASE_URL'
    exit 1
}
$dbUser = $Matches['user']; $oldPass = $Matches['pass']
$dbHost = $Matches['host']; $dbPort = $Matches['port']; $dbName = $Matches['db']

# --- new password: URL-safe characters only (it goes inside DATABASE_URL) ---
if (-not $NewPassword) {
    $alphabet = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    $NewPassword = -join (1..24 | ForEach-Object { $alphabet[(Get-Random -Maximum $alphabet.Length)] })
}
if ($NewPassword -notmatch '^[A-Za-z0-9._-]{8,}$') {
    Write-Error 'NewPassword must be 8+ chars of A-Z a-z 0-9 . _ - (it is embedded in a URL)'
    exit 1
}

# --- locate psql ---
$psql = 'E:\AI\Postgres\bin\psql.exe'
if (-not (Test-Path -LiteralPath $psql)) {
    $cmd = Get-Command psql.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error 'psql.exe not found'; exit 1 }
    $psql = $cmd.Source
}

Write-Host ("root      : " + $Root)
Write-Host ("endpoint  : {0}:{1}/{2} as {3}" -f $dbHost, $dbPort, $dbName, $dbUser)
Write-Host ("old pass  : " + ('*' * [Math]::Min($oldPass.Length, 8)) + " (kept as is until changed)")
Write-Host ("new pass  : " + $NewPassword)

if ($DryRun) {
    Write-Host 'DRY RUN - nothing was changed.'
    exit 0
}

# --- 1) change password in PostgreSQL ---
$escaped = $NewPassword.Replace("'", "''")
$sql = 'ALTER ROLE "{0}" WITH PASSWORD {1};' -f $dbUser, ("'" + $escaped + "'")
$env:PGPASSWORD = $oldPass
& $psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -v ON_ERROR_STOP=1 -c $sql
if ($LASTEXITCODE -ne 0) {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    Write-Error 'ALTER ROLE failed (old password wrong, or role not allowed to change it)'
    exit 1
}
Write-Host 'OK: password changed in PostgreSQL'

# --- 2) rewrite .env (same layout, UTF-8 without BOM) ---
$newText = $text.Replace(':' + $oldPass + '@', ':' + $NewPassword + '@')
if ($newText -eq $text) {
    Write-Error 'could not rewrite DATABASE_URL in .env'
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
    exit 1
}
[System.IO.File]::WriteAllText($EnvFile, $newText, (New-Object System.Text.UTF8Encoding($false)))
Write-Host 'OK: .env updated'

# --- 3) verify the new credential ---
$env:PGPASSWORD = $NewPassword
$check = & $psql -h $dbHost -p $dbPort -U $dbUser -d $dbName -t -A -c 'SELECT 1;'
$ok = ($LASTEXITCODE -eq 0) -and ($check.Trim() -eq '1')
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
if (-not $ok) { Write-Error 'new password verification failed'; exit 1 }
Write-Host 'OK: connection verified with the new password'

Write-Host ''
Write-Host 'NEXT: restart the ERP backend so it re-reads .env.'
Write-Host '      netstat -ano | findstr :8010    then    taskkill /PID <pid> /F'
Write-Host 'NOTE: pgAdmin / DBeaver saved connections must be updated too.'
Write-Host ('NEW PASSWORD: ' + $NewPassword)
exit 0
