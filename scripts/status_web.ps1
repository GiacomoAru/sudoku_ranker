$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
. (Join-Path $PSScriptRoot "web_common.ps1")

$port = Get-SudokuWebPort
$listenerLines = Get-SudokuWebListeners -Port $port

if ($listenerLines.Count -eq 0) {
    Write-Host "Server fermo: la porta $port è libera."
    exit 1
}

$listenerLine = $listenerLines[0].Line
$null = $listenerLine -match "(\d+)\s*$"
$ownerProcessId = [int]$Matches[1]
$process = Get-Process -Id $ownerProcessId -ErrorAction SilentlyContinue
Write-Host (
    "Porta $port in ascolto - PID $ownerProcessId " +
    "($($process.ProcessName))"
)

$publicUrl = Get-SudokuPublicUrl -ProjectRoot $projectRoot
if ($publicUrl) {
    Write-Host "URL PUBBLICO: $publicUrl"
    $tunnelPidPath = Join-Path $projectRoot ".sudoku-web-tunnel.pid"
    if (Test-Path -LiteralPath $tunnelPidPath) {
        $tunnelProcessId = [int](
            Get-Content -LiteralPath $tunnelPidPath -Raw
        ).Trim()
        $tunnelProcess = Get-Process `
            -Id $tunnelProcessId `
            -ErrorAction SilentlyContinue
        if (
            $null -eq $tunnelProcess -or
            $tunnelProcess.ProcessName -notlike "cloudflared*"
        ) {
            Write-Warning "Il link esiste, ma il tunnel non risulta attivo."
        }
        else {
            Write-Host "Tunnel attivo - PID $tunnelProcessId"
        }
    }
}

try {
    $health = Invoke-SudokuWebHealth -Port $port -TimeoutSec 2
    $health | ConvertTo-Json -Depth 5
    exit 0
}
catch {
    Write-Warning (
        "La porta è aperta, ma health non risponde. Se il server è " +
        "protetto, reimposta SUDOKU_WEB_ACCESS_PASSWORD in questo terminale."
    )
    exit 2
}
