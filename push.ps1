# push.ps1 -- sanity-check, commit and push.
#
#   powershell -ExecutionPolicy Bypass -File push.ps1 "commit message"

param([string]$Message = "update")

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Nothing private ever goes up: these are git-ignored, this is the second lock.
foreach ($p in @(".env", "config.json", "vault")) {
  if (git ls-files --error-unmatch $p 2>$null) {
    Write-Host "REFUSING: $p is tracked by git. Remove it: git rm -r --cached $p" -ForegroundColor Red
    exit 1
  }
}

$leaks = Select-String -Path (git ls-files) -Pattern "gsk_[A-Za-z0-9]{20,}" -ErrorAction SilentlyContinue
if ($leaks) {
  Write-Host "REFUSING: an API key appears in a tracked file:" -ForegroundColor Red
  $leaks | ForEach-Object { Write-Host "  $($_.Path):$($_.LineNumber)" }
  exit 1
}

python -c "import ast,pathlib,sys; [ast.parse(p.read_text(encoding='utf-8'), str(p)) for p in pathlib.Path('.').rglob('*.py')]"
if ($LASTEXITCODE -ne 0) { Write-Host "python syntax check failed" -ForegroundColor Red; exit 1 }

git add -A
git commit -m $Message
git push
Write-Host "pushed." -ForegroundColor Green
