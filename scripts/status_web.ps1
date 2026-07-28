$listenerLines = @(
    netstat -ano -p tcp |
        Select-String -Pattern "^\s*TCP\s+\S+:8000\s+\S+\s+LISTENING\s+(\d+)\s*$"
)

if ($listenerLines.Count -eq 0) {
    Write-Host "Server fermo: la porta 8000 è libera."
    exit 1
}

$listenerLine = $listenerLines[0].Line
$null = $listenerLine -match "(\d+)\s*$"
$ownerProcessId = [int]$Matches[1]
$process = Get-Process -Id $ownerProcessId -ErrorAction SilentlyContinue
Write-Host "Porta 8000 in ascolto - PID $ownerProcessId ($($process.ProcessName))"

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/health" -TimeoutSec 2
    $health | ConvertTo-Json -Depth 5
    exit 0
}
catch {
    Write-Warning "La porta è aperta, ma l'endpoint health non risponde: $($_.Exception.Message)"
    exit 2
}
