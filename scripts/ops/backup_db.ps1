# ERP nightly backup: PostgreSQL dump + data/ attachment archive.
# Keep this file pure ASCII: PowerShell 5.1 reads .ps1 as ANSI.
# Credentials are read from <root>\.env, so no secret is stored in this file.
# Called by backup\backup.ps1 (wrapper kept for the scheduled task).

$ErrorActionPreference = 'Stop'
$Keep = 14

# --- resolve project root (walk up until .env is found) ---
$Root = $PSScriptRoot
while ($Root -and -not (Test-Path -LiteralPath (Join-Path $Root '.env'))) {
    $Root = Split-Path -Parent $Root
}
if (-not $Root) { Write-Error '.env not found, cannot resolve project root'; exit 1 }

$EnvFile   = Join-Path $Root '.env'
$BackupDir = Join-Path $Root 'backup'
$DataDir   = Join-Path $Root 'data'
$Stamp     = Get-Date -Format 'yyyyMMdd_HHmmss'

if (-not (Test-Path -LiteralPath $BackupDir)) {
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
}

# --- parse DATABASE_URL from .env ---
$text = Get-Content -LiteralPath $EnvFile -Raw
if ($text -notmatch '(?m)^\s*DATABASE_URL\s*=\s*(\S+)\s*$') {
    Write-Error 'DATABASE_URL missing in .env'
    exit 1
}
$dsn = $Matches[1]
if ($dsn -notmatch '^[^:]+://(?<user>[^:]+):(?<pass>[^@]+)@(?<host>[^:/]+):(?<port>\d+)/(?<db>[^?]+)') {
    Write-Error 'Cannot parse DATABASE_URL'
    exit 1
}
$dbUser = $Matches['user']; $dbPass = $Matches['pass']
$dbHost = $Matches['host']; $dbPort = $Matches['port']; $dbName = $Matches['db']

# --- locate pg_dump ---
$PgDump = 'E:\AI\Postgres\bin\pg_dump.exe'
if (-not (Test-Path -LiteralPath $PgDump)) {
    $cmd = Get-Command pg_dump.exe -ErrorAction SilentlyContinue
    if (-not $cmd) { Write-Error 'pg_dump.exe not found'; exit 1 }
    $PgDump = $cmd.Source
}

# --- 1) database dump ---
$DumpFile = Join-Path $BackupDir "erp_$Stamp.dump"
$env:PGPASSWORD = $dbPass
& $PgDump -h $dbHost -p $dbPort -U $dbUser -d $dbName -F c -f $DumpFile
$dumpOk = ($LASTEXITCODE -eq 0)
Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue

# --- 2) attachments (contract / invoice originals live only on disk) ---
$zipOk = $true
$ZipFile = Join-Path $BackupDir "data_$Stamp.zip"
if (Test-Path -LiteralPath $DataDir) {
    try {
        Compress-Archive -Path $DataDir -DestinationPath $ZipFile -CompressionLevel Optimal -Force
    } catch {
        $zipOk = $false
        Write-Warning("data archive failed: " + $_.Exception.Message)
    }
}

# --- 3) retention: keep latest $Keep of each kind ---
# Only touch files this script creates (erp_yyyyMMdd_HHmmss.dump / data_yyyyMMdd_HHmmss.zip).
# Milestone copies (erp_20261019_final.dump, erp_20261021_1500_pre_autofix.dump,
# erp_*_v51.dump ...) are NEVER deleted: they are documented restore points.
Get-ChildItem -LiteralPath $BackupDir -Filter 'erp_*.dump' |
    Where-Object { $_.BaseName -match '^erp_\d{8}_\d{6}$' } |
    Sort-Object Name -Descending | Select-Object -Skip $Keep |
    Remove-Item -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $BackupDir -Filter 'data_*.zip' |
    Where-Object { $_.BaseName -match '^data_\d{8}_\d{6}$' } |
    Sort-Object Name -Descending | Select-Object -Skip $Keep |
    Remove-Item -Force -ErrorAction SilentlyContinue

# --- 4) history log ---
$status = 'OK'
if (-not $dumpOk) { $status = 'FAILED(dump)' }
elseif (-not $zipOk) { $status = 'PARTIAL(zip)' }
$line = '{0} {1} dump={2} zip={3}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $status, (Split-Path $DumpFile -Leaf), (Split-Path $ZipFile -Leaf)
Add-Content -LiteralPath (Join-Path $BackupDir 'backup_history.log') -Value $line

if (-not $dumpOk) { Write-Error 'pg_dump failed'; exit 1 }
Write-Host $line
exit 0
