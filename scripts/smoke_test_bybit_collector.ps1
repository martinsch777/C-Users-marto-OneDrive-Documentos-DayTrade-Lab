param(
    [ValidateRange(1, 1440)]
    [int]$DurationMinutes = 5,
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
if (-not (Test-Path -LiteralPath $python)) {
    throw "Smoke test couldn't locate virtual-environment Python."
}

Write-Host "[Smoke] Running full Bybit connectivity diagnostics..."
$previousErrorAction = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $python -m src.diagnose_bybit_connection --timeout 8
$diagnosticExitCode = $LASTEXITCODE
$ErrorActionPreference = $previousErrorAction
if ($diagnosticExitCode -ne 0) {
    Write-Warning (
        "The diagnostic wasn't entirely successful. The collector will run " +
        "so REST-only and WebSocket-unstable states remain distinguishable."
    )
}

& (Join-Path $PSScriptRoot "run_bybit_microstructure_collector.ps1") `
    -DurationMinutes $DurationMinutes -Symbols $Symbols
if ($LASTEXITCODE -ne 0) {
    throw "Limited-duration collector run failed."
}

$dataRoot = Join-Path $ProjectRoot "data\forward_microstructure\bybit"
$outputRoot = Join-Path $ProjectRoot "outputs\microstructure_collector"
$logRoot = Join-Path $ProjectRoot "logs\microstructure_collector"
foreach ($path in @($dataRoot, $outputRoot, $logRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Expected directory wasn't created: $path"
    }
}

$statusPath = Join-Path $outputRoot "collector_status.csv"
$status = Import-Csv -LiteralPath $statusPath | Select-Object -Last 1
foreach ($field in @("orders_sent", "broker_connected", "api_keys_used")) {
    if ([string]$status.$field -ne "False") {
        throw "Unsafe collector status: $field=$($status.$field)"
    }
}
& $python -m src.cli safety
if ($LASTEXITCODE -ne 0) {
    throw "Global safety validation failed."
}

$durationSeconds = $DurationMinutes * 60
& $python -m src.microstructure_collector_cli stability `
    --duration-seconds $durationSeconds `
    --symbols $Symbols
if ($LASTEXITCODE -ne 0) {
    throw "Stability report generation failed."
}
$stabilityPath = Join-Path $outputRoot "websocket_stability_report.json"
$stability = Get-Content -LiteralPath $stabilityPath -Raw | ConvertFrom-Json

$verification = @'
from pathlib import Path
import pandas as pd
from src.config import load_config

security = load_config("config.yaml").security
for field in (
    "orders_sent",
    "broker_connected",
    "live_trading_enabled",
    "paper_internal_enabled",
    "paper_broker_enabled",
):
    if security[field]:
        raise SystemExit(f"unsafe global setting: {field}=True")

root = Path("data/forward_microstructure/bybit")
keys = {
    "orderbook.csv": ["symbol", "sequence"],
    "trade.csv": ["symbol", "trade_id"],
    "ticker.csv": ["symbol", "exchange_timestamp_utc"],
    "liquidation.csv": [
        "symbol", "exchange_timestamp_utc",
        "liquidated_position_side", "size", "bankruptcy_price",
    ],
    "kline.csv": ["symbol", "start_utc", "confirmed"],
}
for name, columns in keys.items():
    path = root / name
    if not path.exists() or path.stat().st_size == 0:
        continue
    frame = pd.read_csv(path)
    present = [column for column in columns if column in frame.columns]
    if present and frame.duplicated(present).any():
        raise SystemExit(f"duplicate records detected in {name}: {present}")
print("deduplication=OK")
'@
$verification | & $python -
if ($LASTEXITCODE -ne 0) {
    throw "Collector deduplication verification failed."
}

$logFiles = Get-ChildItem -LiteralPath $logRoot -File -ErrorAction Stop
if (-not $logFiles) {
    throw "No collector log was created."
}
if ($stability.outcome -eq "PASS_WEBSOCKET_STABLE") {
    $rawFiles = Get-ChildItem -LiteralPath $dataRoot -Filter "*.csv" -File
    if (-not $rawFiles -or -not ($rawFiles | Where-Object Length -gt 100)) {
        throw "Stable WebSocket reported but no persisted CSV has records."
    }
    Write-Host "[Smoke] PASS_WEBSOCKET_STABLE" -ForegroundColor Green
    exit 0
}
if ($stability.outcome -eq "PASS_REST_ONLY_FALLBACK") {
    Write-Host (
        "[Smoke] PASS_REST_ONLY_FALLBACK - useful for diagnostics, " +
        "not ready for long WebSocket collection."
    ) -ForegroundColor Yellow
    exit 0
}
throw (
    "[Smoke] $($stability.outcome) - " +
    "recommendation=$($stability.recommendation)"
)
