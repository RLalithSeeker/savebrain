# schedule_windows.ps1 -- make it weekly and hands-off.
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_windows.ps1 -Day Saturday -Time 09:00
#
# Turn it off again:
#   Unregister-ScheduledTask -TaskName SaveBrainWeekly -Confirm:$false
# Test it right now:
#   Start-ScheduledTask -TaskName SaveBrainWeekly

param(
  [string]$Day  = "Sunday",
  [string]$Time = "18:00",
  [string]$TaskName = "SaveBrainWeekly"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$script = Join-Path $PSScriptRoot "run_once.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`"" `
  -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $Time
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
  -Settings $settings -Description "SaveBrain: collect saved posts and write notes" -Force | Out-Null

Write-Host "registered '$TaskName' for every $Day at $Time" -ForegroundColor Green
Write-Host "test it with:  Start-ScheduledTask -TaskName $TaskName"
Write-Host "remove it with: Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
