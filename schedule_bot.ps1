# Register the bot to start at logon and stay running.
#
#   powershell -ExecutionPolicy Bypass -File schedule_bot.ps1
#
# Remove with:  Unregister-ScheduledTask -TaskName BuzzitBot -Confirm:$false

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$name = 'BuzzitBot'

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\run_bot.ps1`"" `
    -WorkingDirectory $here

$trigger = New-ScheduledTaskTrigger -AtLogOn

# ponytail: no ExecutionTimeLimit. The default is 3 days, after which Windows
# would kill a perfectly healthy bot and /post would start failing for no
# visible reason. This task is meant to run forever.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew

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
    -Description 'Buzzit Discord bot: /post to generate and approve videos' | Out-Null

"registered '$name' -- starts at logon, restarts if it dies"
""
"  start now :  Start-ScheduledTask -TaskName $name"
"  stop      :  Stop-ScheduledTask -TaskName $name"
"  log       :  $here\logs\bot.log"
