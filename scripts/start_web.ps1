param(
    [switch]$Background,
    [ValidateSet("local", "lan", "internet")]
    [string]$Exposure
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "web_common.ps1")

$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$pidFilePath = Join-Path $projectRoot ".sudoku-web.pid"
$port = Get-SudokuWebPort

if ($PSBoundParameters.ContainsKey("Exposure")) {
    $env:SUDOKU_WEB_EXPOSURE = $Exposure
    if ($Exposure -eq "internet") {
        $env:SUDOKU_WEB_HOST = "127.0.0.1"
    }
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Ambiente virtuale non trovato: $pythonPath"
}

$listenerLines = Get-SudokuWebListeners -Port $port
if ($listenerLines.Count -gt 0) {
    $listenerLine = $listenerLines[0].Line
    $null = $listenerLine -match "(\d+)\s*$"
    $ownerProcessId = [int]$Matches[1]
    $owner = Get-Process -Id $ownerProcessId -ErrorAction SilentlyContinue
    throw (
        "La porta $port è già occupata dal PID $ownerProcessId " +
        "($($owner.ProcessName))."
    )
}

if (-not $Background) {
    Write-Host "Avvio server in primo piano."
    Write-Host "Questo terminale resta occupato. Premi Ctrl+C per arrestare."
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

for ($attempt = 0; $attempt -lt 160; $attempt++) {
    Start-Sleep -Milliseconds 250
    try {
        $health = Invoke-SudokuWebHealth -Port $port -TimeoutSec 1
        $activeListener = (
            Get-SudokuWebListeners -Port $port |
                Select-Object -First 1
        )
        $null = $activeListener.Line -match "(\d+)\s*$"
        $activeProcessId = [int]$Matches[1]
        Set-Content `
            -LiteralPath $pidFilePath `
            -Value $activeProcessId `
            -Encoding ascii

        Write-Host "Server avviato in background. PID: $activeProcessId"
        Write-Host (
            "Modalità: $($health.exposure_mode) - " +
            "http://127.0.0.1:$port"
        )

        if ($health.exposure_mode -eq "internet") {
            $publicUrl = Get-SudokuPublicUrl -ProjectRoot $projectRoot
            if ($publicUrl) {
                Write-Host ""
                Write-Host "URL PUBBLICO: $publicUrl"
                Write-Host (
                    "Utente: " +
                    $(if ($env:SUDOKU_WEB_ACCESS_USERNAME) {
                        $env:SUDOKU_WEB_ACCESS_USERNAME
                    }
                    else {
                        "sudoku"
                    })
                )
                Write-Host (
                    "Apri il link dal telefono, anche fuori dalla Wi-Fi. " +
                    "Al primo accesso il DNS può richiedere 5-10 secondi."
                )
            }
        }
        exit 0
    }
    catch {
        if ($serverProcess.HasExited) {
            Remove-Item `
                -LiteralPath $pidFilePath `
                -Force `
                -ErrorAction SilentlyContinue
            Stop-SudokuWebTunnel -ProjectRoot $projectRoot
            throw (
                "Il server si è chiuso durante l'avvio " +
                "(exit code $($serverProcess.ExitCode)). " +
                "Avvialo in primo piano per leggere il messaggio completo."
            )
        }
    }
}

Stop-Process -Id $serverProcess.Id -ErrorAction SilentlyContinue
Stop-SudokuWebTunnel -ProjectRoot $projectRoot
Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
throw "Il server non ha risposto entro 40 secondi ed è stato arrestato."
