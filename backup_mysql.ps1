param(
    [string]$OutputDirectory = ".\backups"
)

$ErrorActionPreference = "Stop"
New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null

$envFile = Join-Path (Get-Location) ".env"
if (!(Test-Path $envFile)) { throw ".env was not found" }

$settings = @{}
Get-Content $envFile | ForEach-Object {
    if ($_ -match '^\s*([^#=]+)=(.*)$') { $settings[$matches[1].Trim()] = $matches[2].Trim() }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupFile = Join-Path $OutputDirectory "$($settings['DB_NAME'])-$stamp.sql"
& mysqldump --user=$($settings['DB_USER']) --password=$($settings['DB_PASSWORD']) --host=$($settings['DB_HOST']) $($settings['DB_NAME']) | Out-File -Encoding utf8 $backupFile
Write-Output "Backup created: $backupFile"
