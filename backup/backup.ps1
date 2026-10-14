# ERP database daily backup: pg_dump to this script's own folder, keep latest 14 copies
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads .ps1 as ANSI and
# Chinese path literals (like E:\AI\ERP...) would be corrupted to mojibake.
$ErrorActionPreference = 'Stop'
$PgDump = 'E:\AI\Postgres\bin\pg_dump.exe'
$BackupDir = $PSScriptRoot
$env:PGPASSWORD = 'erp123456'

$Stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
if (-not (Test-Path $BackupDir)) { New-Item -ItemType Directory -Force $BackupDir | Out-Null }

& $PgDump -h 127.0.0.1 -U erp -d erp -F c -f "$BackupDir\erp_$Stamp.dump"
if ($LASTEXITCODE -ne 0) { Write-Error "pg_dump failed with exit code $LASTEXITCODE"; exit 1 }

# Keep only the latest 14 backups
Get-ChildItem $BackupDir -Filter 'erp_*.dump' | Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item -Force
