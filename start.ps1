# Smart Krishi - start everything (server + kiosk link). Same as Campus Mithra's start.ps1.
#
#   .\start.ps1              server + push-to-talk client on COM9
#   .\start.ps1 -Port COM5   a different ESP32 port
#   .\start.ps1 -NoEsp32     no kiosk; PC earphone mic + Ctrl+Alt+4, PC speakers
#
# Opens two windows: the server log, and the talk window. Then hold the button
# on the kiosk, ask your question, and let go - Smart Krishi does the rest.
#
# If PowerShell refuses to run this, once per terminal:
#   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass

param(
    [string]$Port = "COM9",
    [switch]$NoEsp32
)

$root = $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "No virtual environment at $py" -ForegroundColor Red
    Write-Host "Create it first:  python -m venv .venv; .\.venv\Scripts\pip install -r requirements.txt"
    exit 1
}

# 1. Stop earlier copies. An old server would keep port 8001 (and run stale
#    code), an old client would keep COM9 and the hotkey.
$old = Get-CimInstance Win32_Process | Where-Object {
    $_.ExecutablePath -eq $py -and $_.CommandLine -match 'app\.py|krishi_client\.py'
}
foreach ($p in $old) {
    Write-Host "Stopping old $($p.ProcessId): $($p.CommandLine.Split(' ')[-1])"
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}
if ($old) { Start-Sleep -Seconds 1 }

# 2. The server, in its own window so its log stays visible.
$serverCmd = "`$host.UI.RawUI.WindowTitle = 'Smart Krishi - server'; " +
             "Set-Location '$root\server'; & '$py' app.py"
Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $serverCmd

Write-Host "Starting the server" -NoNewline
$up = $false
for ($i = 0; $i -lt 60; $i++) {
    try {
        $h = Invoke-RestMethod http://127.0.0.1:8001/api/krishi/health -TimeoutSec 2
        $up = $true
        break
    } catch {
        Write-Host "." -NoNewline
        Start-Sleep -Seconds 1
    }
}
Write-Host ""
if (-not $up) {
    Write-Host "The server did not come up - read the server window for the error." -ForegroundColor Red
    exit 1
}
Write-Host "Server up: $($h.chunks) chunks, model $($h.model), speech-to-text $($h.stt)" -ForegroundColor Green

# 3. The talk window.
$esp = if ($NoEsp32) { "none" } else { $Port }
$clientCmd = "`$env:PYTHONIOENCODING = 'utf-8'; " +
             "`$host.UI.RawUI.WindowTitle = 'Smart Krishi - hold the kiosk button to talk'; " +
             "Set-Location '$root'; & '$py' krishi_client.py --esp32 $esp"
Start-Process powershell -ArgumentList '-NoExit', '-NoProfile', '-Command', $clientCmd

Write-Host ""
Write-Host "Ready. Hold the kiosk button, ask your question, then let go." -ForegroundColor Cyan
Write-Host "(No kiosk? Run: python krishi_client.py --pc-mic   for the earphone mic + Ctrl+Alt+4)"
