# DEV ONLY. Product scheduling is makeo/scheduler.py on the Makeo worker host.
# Register (or update) the 7pm daily task. Run once, from an ADMIN PowerShell:
#
#   powershell -ExecutionPolicy Bypass -File schedule_daily.ps1
#
# Remove with:  Unregister-ScheduledTask -TaskName BuzzitDaily -Confirm:$false

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = 'BuzzitDaily'
$time = '19:00'

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$here\run_daily.ps1`"" `
    -WorkingDirectory $here

$trigger = New-ScheduledTaskTrigger -Daily -At $time

# ponytail: RunOnlyIfNetworkAvailable + StartWhenAvailable. The run needs the
# internet (RSS, Gemini, Flow, Discord, Instagram) and the machine may be asleep
# or off at 7pm -- StartWhenAvailable catches up on the next wake instead of
# silently skipping the day.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 3) `
    -MultipleInstances IgnoreNew

# Interactive logon, NOT SYSTEM: the run drives Chrome with the logged-in Google
# profile in .chrome-profile/. As SYSTEM there is no user session and Flow fails.
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    "removed existing task"
}

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'Buzzit: generate daily trend video, notify Discord for approval' | Out-Null

"registered '$name' -- runs daily at $time as $env:USERNAME"
""
"  test now :  Start-ScheduledTask -TaskName $name"
"  status   :  Get-ScheduledTaskInfo -TaskName $name"
"  logs     :  $here\logs\"
"  remove   :  Unregister-ScheduledTask -TaskName $name -Confirm:`$false"
