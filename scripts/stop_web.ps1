$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$pidFilePath = Join-Path $projectRoot ".sudoku-web.pid"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2
}
catch {
    Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
    Write-Host "Nessun server Sudoku raggiungibile sulla porta 8000."
    exit 0
}

$listenerLines = @(
    netstat -ano -p tcp |
        Select-String -Pattern "^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+(\d+)\s*$"
)
if ($health.status -ne "ok" -or $health.archive_profile -ne "online") {
    throw "La porta 8000 non espone il server Sudoku online; arresto interrotto."
}

if ($listenerLines.Count -eq 0) {
    throw "Il server risponde, ma il proprietario della porta 8000 non è rilevabile."
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
        throw "Il PID $processId non è il server Sudoku; arresto interrotto."
    }

    Stop-Process -Id $processId -ErrorAction Stop
    Write-Host "Server Sudoku arrestato. PID: $processId"
}

Remove-Item -LiteralPath $pidFilePath -Force -ErrorAction SilentlyContinue
