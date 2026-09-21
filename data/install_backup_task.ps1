param(
    [string]$Python = 'python',
    [string]$Destination = "$env:USERPROFILE\Documents\Letters-from-the-World\backups"
)
$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script = Join-Path $root 'scripts\backup_local.py'
$pythonPath = (Get-Command $Python -ErrorAction Stop).Source
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument ('"' + $script + '" --dest "' + $Destination + '"')
$trigger = New-ScheduledTaskTrigger -Daily -At 11:00AM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName 'LettersFromTheWorld-Backup' -Action $action -Trigger $trigger -Settings $settings -Description 'Download Kindle brief EPUB backups from GitHub Actions' -Force | Out-Null
Write-Host "已设置每天 11:00 同步；备份目录：$Destination"
