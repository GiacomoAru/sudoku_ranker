$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "web_common.ps1")

$pidFilePath = Join-Path $projectRoot ".sudoku-web.pid"
$port = Get-SudokuWebPort

try {
    $health = Invoke-SudokuWebHealth -Port $port -TimeoutSec 2
}
catch {
    Write-Host (
        "Impossibile verificare il server Sudoku sulla porta $port. " +
        "Se è protetto, reimposta SUDOKU_WEB_ACCESS_PASSWORD."
    )
    exit 2
}

$listenerLines = Get-SudokuWebListeners -Port $port
if ($health.status -ne "ok" -or $health.archive_profile -ne "online") {
    throw (
        "La porta $port non espone il server Sudoku online; " +
        "arresto interrotto."
    )
}
if ($listenerLines.Count -eq 0) {
    throw "Il server risponde, ma il proprietario della porta non è rilevabile."
}

$processIds = @(
    $listenerLines |
        ForEach-Object {
            if ($_.Line -match "(\d+)\s*$") {
                [int]$Matches[1]
            }
        } |
        Sort-Object -Unique
)

foreach ($processId in $processIds) {
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        continue
    }
    if ($process.ProcessName -notlike "python*") {
        throw (
            "Il PID $processId non è il server Sudoku; " +
            "arresto interrotto."
        )
    }

    Stop-Process -Id $processId -ErrorAction Stop
    Write-Host "Server Sudoku arrestato. PID: $processId"
}

Stop-SudokuWebTunnel -ProjectRoot $projectRoot

Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
