# Runs Stock Ledger in the background as a Windows scheduled task: it starts when the PC starts
# (before anyone logs in), and run-server.cmd starts it again if it ever stops.
# Use the .bat files next to this script, or:  service.ps1 install | restart | stop | uninstall | status
param([ValidateSet('install', 'restart', 'stop', 'uninstall', 'status')][string]$Action = 'status')

$ErrorActionPreference = 'Stop'
$TaskName = 'Stock Ledger'
$App = Split-Path -Parent $PSScriptRoot  # the project folder; this script lives in its windows\ folder
$Py = Join-Path $App '.venv\Scripts\python.exe'
$Runner = Join-Path $PSScriptRoot 'run-server.cmd'

# Managing scheduled tasks and the firewall needs admin rights: ask, and run again in a new window.
$identity = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
if (-not $identity.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process powershell.exe -Verb RunAs -ArgumentList @(
        '-NoProfile', '-ExecutionPolicy', 'Bypass', '-NoExit', '-File', "`"$PSCommandPath`"", $Action)
    exit
}

function Get-Port {
    $ini = Join-Path $App 'settings.ini'
    if (Test-Path $ini) {
        $m = Select-String -Path $ini -Pattern '^\s*port\s*=\s*(\d+)' | Select-Object -First 1
        if ($m) { return [int]$m.Matches[0].Groups[1].Value }
    }
    return 8000
}

function Stop-App {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    # Stop the keep-running loop first, so it doesn't start the app again...
    Get-CimInstance Win32_Process -Filter "Name = 'cmd.exe'" |
        Where-Object { $_.CommandLine -like '*run-server.cmd*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    # ...then whatever is serving the app's port.
    Get-NetTCPConnection -LocalPort (Get-Port) -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2
}

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) { Write-Host 'Stock Ledger service is not installed.'; return }
    $port = Get-Port
    Write-Host "Scheduled task: $($task.State)"
    for ($i = 0; $i -lt 20; $i++) {
        try {
            Invoke-WebRequest "http://localhost:$port/api/auth/state" -UseBasicParsing -TimeoutSec 3 | Out-Null
            Write-Host "Stock Ledger is running: http://localhost:$port" -ForegroundColor Green
            return
        } catch { Start-Sleep -Seconds 2 }
    }
    Write-Host "Stock Ledger is not answering on port $port. Look in $App\data\logs for the reason." -ForegroundColor Red
}

function Install-App {
    if (-not (Test-Path $Py)) {
        Write-Host 'First time: setting up Python and packages...'
        & python -m venv (Join-Path $App '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Python not found. Install it from python.org and tick "Add python.exe to PATH".' }
        & $Py -m pip install -q -r (Join-Path $App 'requirements.txt')
        if ($LASTEXITCODE -ne 0) { throw 'Installing packages failed. Check the internet connection and run this again.' }
    }
    Stop-App
    $taskAction = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$Runner`"" -WorkingDirectory $App
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -MultipleInstances IgnoreNew
    $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $taskAction -Trigger $trigger -Settings $settings `
        -Principal $principal -Force | Out-Null
    # Let phones on the factory Wi-Fi in (private networks only, never public Wi-Fi).
    if (-not (Get-NetFirewallRule -DisplayName $TaskName -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName $TaskName -Direction Inbound -Protocol TCP -LocalPort (Get-Port) `
            -Action Allow -Profile Private | Out-Null
    }
    Start-ScheduledTask -TaskName $TaskName
    Show-Status
}

switch ($Action) {
    'install'   { Install-App }
    'restart'   { Stop-App; Start-ScheduledTask -TaskName $TaskName; Show-Status }
    'stop'      { Stop-App; Write-Host 'Stock Ledger is stopped. It starts again with restart-service.bat or when the PC restarts.' }
    'uninstall' {
        Stop-App
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Remove-NetFirewallRule -DisplayName $TaskName -ErrorAction SilentlyContinue
        Write-Host 'Stock Ledger service removed. Your data in the data folder is untouched.'
    }
    'status'    { Show-Status }
}
