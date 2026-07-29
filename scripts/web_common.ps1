function Get-SudokuWebPort {
    if ($env:SUDOKU_WEB_PORT) {
        return [int]$env:SUDOKU_WEB_PORT
    }
    return 8000
}

function Get-SudokuWebAuthHeaders {
    if (-not $env:SUDOKU_WEB_ACCESS_PASSWORD) {
        return @{}
    }

    $username = if ($env:SUDOKU_WEB_ACCESS_USERNAME) {
        $env:SUDOKU_WEB_ACCESS_USERNAME
    }
    else {
        "sudoku"
    }
    $credentials = "${username}:$($env:SUDOKU_WEB_ACCESS_PASSWORD)"
    $bytes = [Text.Encoding]::UTF8.GetBytes($credentials)
    $encoded = [Convert]::ToBase64String($bytes)
    return @{ Authorization = "Basic $encoded" }
}

function Invoke-SudokuWebHealth {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port,
        [int]$TimeoutSec = 2
    )

    $headers = Get-SudokuWebAuthHeaders
    return Invoke-RestMethod `
        -Uri "http://127.0.0.1:${Port}/api/v1/health" `
        -Headers $headers `
        -TimeoutSec $TimeoutSec
}

function Get-SudokuWebListeners {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Port
    )

    return @(
        netstat -ano -p tcp |
            Select-String -Pattern (
                "^\s*TCP\s+\S+:${Port}\s+\S+\s+LISTENING\s+(\d+)\s*$"
            )
    )
}

function Get-SudokuPublicUrl {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $urlPath = Join-Path $ProjectRoot ".sudoku-web-public-url"
    if (Test-Path -LiteralPath $urlPath) {
        return (Get-Content -LiteralPath $urlPath -Raw).Trim()
    }
    return $null
}

function Stop-SudokuWebTunnel {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ProjectRoot
    )

    $tunnelPidPath = Join-Path $ProjectRoot ".sudoku-web-tunnel.pid"
    $publicUrlPath = Join-Path $ProjectRoot ".sudoku-web-public-url"

    if (Test-Path -LiteralPath $tunnelPidPath) {
        $tunnelProcessId = [int](
            Get-Content -LiteralPath $tunnelPidPath -Raw
        ).Trim()
        $tunnelProcess = Get-Process `
            -Id $tunnelProcessId `
            -ErrorAction SilentlyContinue

        if ($null -ne $tunnelProcess) {
            if ($tunnelProcess.ProcessName -notlike "cloudflared*") {
                throw (
                    "Il PID tunnel $tunnelProcessId non è cloudflared; " +
                    "arresto interrotto."
                )
            }
            Stop-Process -Id $tunnelProcessId -ErrorAction Stop
            Write-Host "Tunnel pubblico arrestato. PID: $tunnelProcessId"
        }
    }

    Remove-Item `
        -LiteralPath $tunnelPidPath `
        -Force `
        -ErrorAction SilentlyContinue
    Remove-Item `
        -LiteralPath $publicUrlPath `
        -Force `
        -ErrorAction SilentlyContinue
}
