param(
    [switch]$Background
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pidFilePath = Join-Path $projectRoot ".sudoku-web.pid"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Ambiente virtuale non trovato: $pythonPath"
}

$listenerLines = @(
    netstat -ano -p tcp |
        Select-String -Pattern "^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+(\d+)\s*$"
)
if ($listenerLines.Count -gt 0) {
    $listenerLine = $listenerLines[0].Line
    $null = $listenerLine -match "(\d+)\s*$"
    $ownerProcessId = [int]$Matches[1]
    $owner = Get-Process -Id $ownerProcessId -ErrorAction SilentlyContinue
    throw "La porta 8000 è già occupata dal PID $ownerProcessId ($($owner.ProcessName))."
}

if (-not $Background) {
    Write-Host "Server in primo piano su http://127.0.0.1:8000"
    Write-Host "Questo terminale resta occupato intenzionalmente. Premi Ctrl+C per arrestare."
    Push-Location $projectRoot
    try {
        & $pythonPath "run_web.py"
    }
    finally {
        Pop-Location
    }
    exit $LASTEXITCODE
}

$serverProcess = Start-Process `
    -FilePath $pythonPath `
    -ArgumentList "run_web.py" `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -PassThru

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 1
        $activeListener = (
            netstat -ano -p tcp |
                Select-String -Pattern "^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+(\d+)\s*$" |
                Select-Object -First 1
        )
        $null = $activeListener.Line -match "(\d+)\s*$"
        $activeProcessId = [int]$Matches[1]
        Set-Content -LiteralPath $pidFilePath -Value $activeProcessId -Encoding ascii
        Write-Host "Server avviato in background. PID: $activeProcessId"
        Write-Host "Stato: $($health.status) - http://127.0.0.1:8000"
        exit 0
    }
    catch {
        # Il processo può impiegare qualche istante prima di accettare richieste.
        if ($serverProcess.HasExited) {
            Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
            throw "Il server si è chiuso durante l'avvio (exit code $($serverProcess.ExitCode))."
        }
    }
}

Stop-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
throw "Il processo è partito ma non ha risposto entro 5 secondi; è stato arrestato."
