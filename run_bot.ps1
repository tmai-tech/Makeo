# Keeps bot.py running. Task Scheduler starts this at logon.
#
#   powershell -ExecutionPolicy Bypass -File run_bot.ps1
#
# ponytail: a restart loop, not a bare `python bot.py`. A dropped websocket or a
# transient Discord outage kills the process, and a dead bot answers /post with
# "The application did not respond" -- silent until someone tries to use it.

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$logDir = Join-Path $here 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory $logDir | Out-Null }
$log = Join-Path $logDir 'bot.log'

while ($true) {
    "=== bot starting $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') ===" |
        Out-File $log -Append -Encoding utf8
    # ponytail: 2>&1 at the cmd level, not PowerShell's *>&1. In PS 5.1 the
    # latter wraps every native stderr line in a NativeCommandError record, so
    # discord.py's INFO logs render as red "errors" in the log.
    & cmd /c "python bot.py 2>&1" | Out-File $log -Append -Encoding utf8
    "=== bot exited (code $LASTEXITCODE), restarting in 15s ===" |
        Out-File $log -Append -Encoding utf8
    Start-Sleep -Seconds 15
}
