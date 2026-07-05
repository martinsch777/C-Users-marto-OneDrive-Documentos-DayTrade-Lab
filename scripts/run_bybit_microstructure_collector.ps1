param(
    [ValidateRange(1, 10080)]
    [int]$DurationMinutes = 10,
    [string[]]$Symbols = @("BTCUSDT"),
    [ValidateSet("ticker", "trades", "orderbook", "liquidation", "kline")]
    [string[]]$Topics = @(),
    [ValidateRange(1, 600)]
    [double]$MaxReconnectBackoffSeconds = 60,
    [switch]$ForceInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

$setupArgs = @{
    PassThru = $true
    ForceInstall = $ForceInstall
}
$setup = & (Join-Path $PSScriptRoot "setup_or_find_venv.ps1") @setupArgs
if (-not $setup -or -not (Test-Path -LiteralPath $setup.PythonPath)) {
    throw "Virtual environment setup didn't return a valid Python path."
}
$python = $setup.PythonPath

& $python -m src.cli safety
if ($LASTEXITCODE -ne 0) {
    throw "Safety configuration validation failed; collector wasn't started."
}

& $python -m src.microstructure_collector_cli init
if ($LASTEXITCODE -ne 0) {
    throw "Collector initialization failed with exit code $LASTEXITCODE."
}

$durationSeconds = $DurationMinutes * 60
$collectorArgs = @(
    "-m", "src.microstructure_collector_cli", "run",
    "--symbols"
) + $Symbols
if ($Topics.Count -gt 0) {
    $collectorArgs += @("--topics") + $Topics
}
$collectorArgs += @(
    "--duration-seconds", [string]$durationSeconds,
    "--max-reconnect-backoff-seconds",
    [string]$MaxReconnectBackoffSeconds,
    "--confirm-public-data-only"
)

Write-Host (
    "[DayTrade Lab] Starting public Bybit collector for " +
    "$DurationMinutes minute(s)."
) -ForegroundColor Green
& $python @collectorArgs
if ($LASTEXITCODE -ne 0) {
    throw "Collector exited with code $LASTEXITCODE."
}

$statusPath = Join-Path $ProjectRoot `
    "outputs\microstructure_collector\collector_status.csv"
if (Test-Path -LiteralPath $statusPath) {
    Import-Csv -LiteralPath $statusPath | Select-Object -Last 1 |
        Format-List
}
