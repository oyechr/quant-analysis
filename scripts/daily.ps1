# Daily check for Windows Task Scheduler: `quant changes` on the watchlist,
# the holdings and the open journal theses. Saves the digest to
# data/_changes/, shows a notification when something is worth a look, and
# appends the run's output to data/_changes/changes.log (trimmed to its last
# $keepLines lines once it passes $maxLogBytes).
#
# Register it once (see the README, "Daily check"). Run it by hand with:
#   powershell -ExecutionPolicy Bypass -File scripts\daily.ps1

$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

$quant = "venv\Scripts\quant.exe"
$log = "data\_changes\changes.log"
$maxLogBytes = 1MB
$keepLines = 5000

# UTF-8 from the first byte (before quant reconfigures its streams), and
# unbuffered, so stdout and stderr land in the log in the order printed
$env:PYTHONUTF8 = "1"
$env:PYTHONUNBUFFERED = "1"

New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
if ((Test-Path $log) -and (Get-Item $log).Length -gt $maxLogBytes) {
    $tail = Get-Content -Encoding utf8 -Tail $keepLines $log
    [System.IO.File]::WriteAllLines((Resolve-Path $log), $tail, (New-Object System.Text.UTF8Encoding $false))
}
"=== $(Get-Date -Format s)" | Out-File -Append -Encoding utf8 $log

# cmd does the redirection, so the log stays UTF-8 and stderr is plain text
cmd /c "$quant -q changes --save --notify >> $log 2>&1"
exit $LASTEXITCODE
