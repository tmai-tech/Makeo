# Wrapper Task Scheduler calls at 19:00. Asks the running bot to do the work.
#
#   powershell -ExecutionPolicy Bypass -File run_daily.ps1
#
# ponytail: drops a .trigger file instead of running the pipeline itself. The
# bot already holds the Discord connection and posts real Approve/Reject
# buttons; the old path spun up a cloudflared tunnel that died mid-wait and
# swallowed an approval click as a 502. One owner of the flow, not two.

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

$logDir = Join-Path $here 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory $logDir | Out-Null }
$log = Join-Path $logDir ("daily-" + (Get-Date -Format 'yyyy-MM-dd-HHmm') + ".log")

"=== $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') scheduled run ===" | Tee-Object $log

# Token check first: a dead IG token means the whole run is wasted effort, and
# it is far better to learn that before spending Flow credits on a video.
$who = & python post_instagram.py --whoami 2>&1
$who | Tee-Object $log -Append
if ($LASTEXITCODE -ne 0) {
    "ABORT: Instagram token invalid -- refresh with --finish-setup" | Tee-Object $log -Append
    exit 1
}

# The bot must be up, or the trigger file just sits there unread.
$botUp = Get-Process python -ErrorAction SilentlyContinue |
         Where-Object { $_.CommandLine -like '*bot.py*' }
if (-not $botUp) {
    "bot not running -- starting it" | Tee-Object $log -Append
    $vbs = Join-Path ([Environment]::GetFolderPath('Startup')) 'BuzzitBot.vbs'
    if (Test-Path $vbs) { Start-Process wscript.exe -ArgumentList "`"$vbs`"" }
    Start-Sleep -Seconds 20
}

New-Item -ItemType File -Path (Join-Path $here '.trigger') -Force | Out-Null
"trigger dropped -- the bot will generate and post the approval card" |
    Tee-Object $log -Append

# Keep a fortnight of logs, drop the rest.
Get-ChildItem $logDir -Filter 'daily-*.log' |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip 14 |
    Remove-Item -Force -ErrorAction SilentlyContinue
