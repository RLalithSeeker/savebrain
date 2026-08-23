# run_once.ps1 -- one unattended cycle on Windows.
#
#   1. starts the bridge in auto-ingest mode (it exits by itself when done)
#   2. opens your Saved page with the #sb-auto fragment, which tells the
#      extension to start collecting without a click
#   3. the bridge ingests, writes notes, and shuts down
#
# The one thing this cannot do for you: stay logged in. If the browser is
# logged out, the extension reports it and the log says so.
#
#   powershell -ExecutionPolicy Bypass -File scripts\run_once.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\run_once.ps1 -Username someone

param(
  [string]$Username = "",
  [string]$Browser  = ""
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cfgPath = Join-Path $root "config.json"

if (-not (Test-Path $cfgPath)) {
  Write-Host "No config.json. Run: python savebrain.py setup" -ForegroundColor Red
  exit 1
}
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json

if (-not $Username) { $Username = $cfg.instagram_username }
if (-not $Username) {
  Write-Host 'Set your handle first: add "instagram_username" to config.json, or pass -Username' -ForegroundColor Red
  exit 1
}
if (-not $Browser) { $Browser = $cfg.browser_command }

$logDir = Join-Path $root ((($cfg.vault_dir) -replace '/', '\') + "\_logs")
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir ("run_" + (Get-Date -Format "yyyyMMdd_HHmmss") + ".log")

Write-Host "starting bridge (auto-ingest)..."
$bridge = Start-Process -FilePath "python" `
  -ArgumentList @("savebrain.py", "auto") `
  -WorkingDirectory $root -PassThru -WindowStyle Hidden `
  -RedirectStandardOutput $log -RedirectStandardError ($log + ".err")

Start-Sleep -Seconds 3

$url = "https://www.instagram.com/$Username/saved/all-posts/#sb-auto"
Write-Host "opening $url"
if ($Browser) { Start-Process $Browser $url } else { Start-Process $url }

Write-Host "waiting for the collection + ingest to finish (log: $log)"
$bridge.WaitForExit(3600000) | Out-Null
Write-Host "done. See $log"
