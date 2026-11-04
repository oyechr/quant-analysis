# Daily check for Windows Task Scheduler: `quant changes` on the watchlist,
# the holdings and the open journal theses. Saves the digest to
# data/_changes/, shows a notification when something is worth a look, and
# appends the run's output to data/_changes/changes.log.
#
# Register it once (see the README, "Daily check"). Run it by hand with:
#   powershell -ExecutionPolicy Bypass -File scripts\daily.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$quant = "venv\Scripts\quant.exe"
$log = "data\_changes\changes.log"
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
"=== $(Get-Date -Format s)" | Out-File -Append -Encoding utf8 $log

# cmd does the redirection, so the log stays UTF-8 and stderr is plain text
cmd /c "$quant -q changes --save --notify >> $log 2>&1"
exit $LASTEXITCODE
