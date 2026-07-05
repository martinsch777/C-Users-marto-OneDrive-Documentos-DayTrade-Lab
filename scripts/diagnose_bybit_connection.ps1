param(
    [string]$Symbol = "BTCUSDT",
    [int]$TimeoutSeconds = 8,
    [switch]$RestOnly
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$OutputRoot = Join-Path $ProjectRoot "outputs\microstructure_collector"
$DataRoot = Join-Path $ProjectRoot "data\forward_microstructure\bybit"
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null
New-Item -ItemType Directory -Force -Path $DataRoot | Out-Null

$results = [System.Collections.Generic.List[object]]::new()

function Add-DiagnosticResult {
    param(
        [string]$Test,
        [string]$Target,
        [string]$Status,
        [string]$ErrorCode,
        [string]$Details
    )
    $results.Add([pscustomobject]@{
        test = $Test
        target = $Target
        status = $Status
        error_code = $ErrorCode
        details = $Details
    })
}

foreach ($hostName in @("api.bybit.com", "stream.bybit.com")) {
    try {
        $addresses = Resolve-DnsName -Name $hostName -Type A -ErrorAction Stop |
            Where-Object { $_.PSObject.Properties.Name -contains "IPAddress" } |
            Select-Object -ExpandProperty IPAddress -Unique
        Add-DiagnosticResult "powershell_dns" $hostName "PASS" "" (
            "addresses=" + ($addresses -join ",")
        )
    }
    catch {
        Add-DiagnosticResult "powershell_dns" $hostName "FAIL" "DNS_FAILED" (
            $_.Exception.GetType().Name + ": " + $_.Exception.Message
        )
    }
}

$httpsTarget = "https://api.bybit.com/v5/market/time"
try {
    $response = Invoke-RestMethod -Uri $httpsTarget -Method Get `
        -TimeoutSec $TimeoutSeconds -ErrorAction Stop
    if ($response.retCode -eq 0) {
        Add-DiagnosticResult "powershell_https" $httpsTarget "PASS" "" (
            "retCode=0 server_time_ms=" + $response.time
        )
    }
    else {
        Add-DiagnosticResult "powershell_https" $httpsTarget "FAIL" `
            "HTTPS_BLOCKED" ("retCode=" + $response.retCode)
    }
}
catch {
    Add-DiagnosticResult "powershell_https" $httpsTarget "FAIL" `
        "HTTPS_BLOCKED" (
            $_.Exception.GetType().Name + ": " + $_.Exception.Message
        )
}

foreach ($hostName in @("api.bybit.com", "stream.bybit.com")) {
    try {
        $connected = Test-NetConnection -ComputerName $hostName -Port 443 `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($connected) {
            Add-DiagnosticResult "powershell_tcp_443" "$hostName`:443" `
                "PASS" "" "connected"
        }
        else {
            Add-DiagnosticResult "powershell_tcp_443" "$hostName`:443" `
                "FAIL" "TCP_443_BLOCKED" "Test-NetConnection returned false"
        }
    }
    catch {
        Add-DiagnosticResult "powershell_tcp_443" "$hostName`:443" `
            "FAIL" "TCP_443_BLOCKED" (
                $_.Exception.GetType().Name + ": " + $_.Exception.Message
            )
    }
}

$writeProbe = Join-Path $DataRoot ".powershell_write_probe.tmp"
try {
    Set-Content -LiteralPath $writeProbe -Value "public-data-write-probe" `
        -Encoding UTF8 -ErrorAction Stop
    Remove-Item -LiteralPath $writeProbe -Force -ErrorAction Stop
    Add-DiagnosticResult "powershell_filesystem_write" $DataRoot "PASS" "" `
        "write/delete ok"
}
catch {
    Add-DiagnosticResult "powershell_filesystem_write" $DataRoot "FAIL" `
        "FILE_WRITE_FAILED" (
            $_.Exception.GetType().Name + ": " + $_.Exception.Message
        )
}

$pythonVersion = (& python --version 2>&1) -join " "
Add-DiagnosticResult "python_version" "python" "INFO" "" $pythonVersion

$packageScript = @'
import importlib.metadata, json
names = ["websockets", "websocket-client", "aiohttp"]
versions = {}
for name in names:
    try:
        versions[name] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        versions[name] = "<not-installed>"
print(json.dumps(versions, sort_keys=True))
'@
$packageVersions = ($packageScript | python - 2>&1) -join " "
Add-DiagnosticResult "python_packages" "local_environment" "INFO" "" `
    $packageVersions

$relevantVariables = @(
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
    "BYBIT_API_KEY", "BYBIT_API_SECRET", "API_KEY", "API_SECRET"
)
foreach ($name in $relevantVariables) {
    $value = [Environment]::GetEnvironmentVariable($name, "Process")
    $state = if ([string]::IsNullOrEmpty($value)) {
        "<unset>"
    }
    else {
        "<set:length=$($value.Length)>"
    }
    Add-DiagnosticResult "environment_variable_redacted" $name "INFO" "" $state
}
$pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
$pathEntries = if ($pathValue) { ($pathValue -split ";").Count } else { 0 }
Add-DiagnosticResult "environment_path" "Path" "INFO" "" `
    "entry_count=$pathEntries; value_not_logged=true"

$pythonReport = Join-Path $OutputRoot "bybit_connection_diagnostic.json"
$arguments = @(
    "-m", "src.diagnose_bybit_connection",
    "--symbol", $Symbol,
    "--timeout", $TimeoutSeconds,
    "--output", $pythonReport
)
if ($RestOnly) {
    $arguments += "--rest-only"
}
& python @arguments
$pythonExitCode = $LASTEXITCODE

if (Test-Path -LiteralPath $pythonReport) {
    try {
        $pythonPayload = Get-Content -LiteralPath $pythonReport -Raw |
            ConvertFrom-Json -ErrorAction Stop
        foreach ($item in $pythonPayload.results) {
            $results.Add($item)
        }
    }
    catch {
        Add-DiagnosticResult "python_report_parse" $pythonReport "FAIL" `
            "UNKNOWN_NETWORK_ERROR" (
                $_.Exception.GetType().Name + ": " + $_.Exception.Message
            )
    }
}
else {
    Add-DiagnosticResult "python_diagnostics" "python_module" "FAIL" `
        "UNKNOWN_NETWORK_ERROR" "Python report was not created"
}

$finalReport = Join-Path $OutputRoot `
    "bybit_connection_diagnostic_powershell.json"
$payload = [ordered]@{
    generated_at_utc = [DateTime]::UtcNow.ToString("o")
    symbol = $Symbol
    python_exit_code = $pythonExitCode
    results = $results
    safety = [ordered]@{
        api_keys_used = $false
        private_values_logged = $false
        broker_connected = $false
        orders_sent = $false
        live_trading_enabled = $false
        paper_internal_enabled = $false
        paper_broker_enabled = $false
        real_leverage_used = $false
    }
}
$payload | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $finalReport -Encoding UTF8

$results |
    Select-Object status, test, target, error_code, details |
    Format-Table -AutoSize
Write-Host "PowerShell report: $finalReport"
Write-Host "Python report:     $pythonReport"
