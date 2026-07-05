param(
    [ValidateSet(1, 2)]
    [int]$DurationMinutesPerPhase = 1,
    [string[]]$Symbols = @("BTCUSDT")
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

$setup = & (Join-Path $PSScriptRoot "setup_or_find_venv.ps1") -PassThru
$python = $setup.PythonPath
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Topic smoke test couldn't locate virtual-environment Python."
}

& $python -m src.cli safety
if ($LASTEXITCODE -ne 0) {
    throw "Safety configuration validation failed."
}
& $python -m src.microstructure_collector_cli init
if ($LASTEXITCODE -ne 0) {
    throw "Collector initialization failed."
}

$phases = @(
    [pscustomobject]@{ Name = "ticker"; Topics = @("ticker") },
    [pscustomobject]@{ Name = "trades"; Topics = @("trades") },
    [pscustomobject]@{ Name = "orderbook"; Topics = @("orderbook") },
    [pscustomobject]@{ Name = "liquidation"; Topics = @("liquidation") },
    [pscustomobject]@{
        Name = "ticker_trades"
        Topics = @("ticker", "trades")
    },
    [pscustomobject]@{
        Name = "ticker_trades_orderbook"
        Topics = @("ticker", "trades", "orderbook")
    },
    [pscustomobject]@{
        Name = "all_topics"
        Topics = @(
            "ticker", "trades", "orderbook", "liquidation", "kline"
        )
    }
)

$durationSeconds = $DurationMinutesPerPhase * 60
$outputRoot = Join-Path $ProjectRoot "outputs\microstructure_collector"
$statusPath = Join-Path $outputRoot "collector_status.csv"
$results = @()

foreach ($phase in $phases) {
    Write-Host (
        "[Topic smoke] phase=$($phase.Name) " +
        "topics=$($phase.Topics -join ',')"
    ) -ForegroundColor Cyan
    $arguments = @(
        "-m", "src.microstructure_collector_cli", "run",
        "--symbols"
    ) + $Symbols + @("--topics") + $phase.Topics + @(
        "--duration-seconds", [string]$durationSeconds,
        "--max-reconnect-backoff-seconds", "10",
        "--confirm-public-data-only"
    )
    & $python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Collector process failed in phase $($phase.Name)."
    }

    $status = Import-Csv -LiteralPath $statusPath | Select-Object -Last 1
    $connected = [int]$status.websocket_connected
    $ack = [string]$status.websocket_subscription_acknowledged -eq "True"
    $received = [int]$status.websocket_messages_received
    $persisted = [int]$status.websocket_messages_persisted
    $errors = [int]$status.websocket_errors
    $reconnects = [int]$status.websocket_reconnects
    $topicOk = (
        $connected -gt 0 -and
        $ack -and
        $errors -le 2 -and
        $reconnects -le 2
    )
    $results += [pscustomobject]@{
        phase = $phase.Name
        topics = $phase.Topics
        connected = ($connected -gt 0)
        ack = $ack
        messages_received = $received
        messages_persisted = $persisted
        errors = $errors
        reconnects = $reconnects
        topic_ok = if ($topicOk) { $phase.Topics } else { @() }
        topic_failed = if ($topicOk) { @() } else { $phase.Topics }
        last_error_code = [string]$status.last_error_code
    }
}

$report = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    duration_minutes_per_phase = $DurationMinutesPerPhase
    symbols = $Symbols
    phases = $results
    all_phases_ok = -not [bool](
        $results | Where-Object { $_.topic_failed.Count -gt 0 }
    )
    safety = [ordered]@{
        orders_sent = $false
        broker_connected = $false
        api_keys_used = $false
        live_trading_enabled = $false
        paper_internal_enabled = $false
        paper_broker_enabled = $false
        real_leverage_used = $false
    }
}
$reportPath = Join-Path $outputRoot "topic_stability_report.json"
$report | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $reportPath -Encoding UTF8
$results | Format-Table `
    phase, connected, ack, messages_received, messages_persisted, `
    errors, reconnects, topic_failed -AutoSize
Write-Host "Report: $reportPath"

if (-not $report.all_phases_ok) {
    throw "One or more public topic phases were unstable."
}
Write-Host "[Topic smoke] PASS - all phases stable." -ForegroundColor Green
