param()

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

$venvRows = @()
$pythonPath = $null
foreach ($name in @(".venv", "venv", "env", ".env")) {
    $root = Join-Path $ProjectRoot $name
    $candidatePython = Join-Path $root "Scripts\python.exe"
    $candidateActivate = Join-Path $root "Scripts\Activate.ps1"
    $valid = (
        (Test-Path -LiteralPath $candidatePython -PathType Leaf) -and
        (Test-Path -LiteralPath $candidateActivate -PathType Leaf)
    )
    $venvRows += [pscustomobject]@{
        Name = $name
        RootExists = Test-Path -LiteralPath $root
        PythonExists = Test-Path -LiteralPath $candidatePython
        ActivateExists = Test-Path -LiteralPath $candidateActivate
        Valid = $valid
    }
    if ($valid -and -not $pythonPath) {
        $pythonPath = $candidatePython
    }
}
if (-not $pythonPath) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $pythonPath = $pythonCommand.Source
    }
}

function Invoke-PythonCheck {
    param([string]$Code)
    if (-not $pythonPath) {
        return [pscustomobject]@{ Success = $false; Output = "Python not found" }
    }
    $output = (& $pythonPath -c $Code 2>&1) -join "`n"
    return [pscustomobject]@{
        Success = ($LASTEXITCODE -eq 0)
        Output = $output
    }
}

$version = Invoke-PythonCheck "import platform; print(platform.python_version())"
$bits = Invoke-PythonCheck "import struct; print(struct.calcsize('P') * 8)"
$pip = if ($pythonPath) {
    (& $pythonPath -m pip --version 2>&1) -join "`n"
} else {
    "Python not found"
}
$pandas = Invoke-PythonCheck "import pandas; print(pandas.__version__)"
$numpy = Invoke-PythonCheck "import numpy; print(numpy.__version__)"
$project = Invoke-PythonCheck (
    "import src; import src.microstructure_collector_cli; " +
    "import src.diagnose_bybit_connection; print('OK')"
)

$files = @(
    "requirements.txt",
    "pyproject.toml",
    "config.yaml",
    "docs\FORWARD_MICROSTRUCTURE_COLLECTOR.md",
    "src\microstructure_collector_cli.py",
    "src\diagnose_bybit_connection.py"
)
$fileRows = foreach ($file in $files) {
    [pscustomobject]@{
        File = $file
        Exists = Test-Path -LiteralPath (Join-Path $ProjectRoot $file)
    }
}

$report = [ordered]@{
    GeneratedAtUtc = [DateTime]::UtcNow.ToString("o")
    CurrentDirectory = (Get-Location).Path
    ProjectRoot = $ProjectRoot
    VirtualEnvironments = $venvRows
    PythonPath = $pythonPath
    PythonVersion = $version.Output
    Python64Bit = ($bits.Success -and $bits.Output.Trim() -eq "64")
    Pip = $pip
    PandasImport = $pandas.Success
    PandasVersionOrError = $pandas.Output
    NumpyImport = $numpy.Success
    NumpyVersionOrError = $numpy.Output
    ProjectModulesImport = $project.Success
    ProjectModulesOutput = $project.Output
    ThreadEnvironment = [ordered]@{
        OPENBLAS_NUM_THREADS = $env:OPENBLAS_NUM_THREADS
        OMP_NUM_THREADS = $env:OMP_NUM_THREADS
        MKL_NUM_THREADS = $env:MKL_NUM_THREADS
        NUMEXPR_NUM_THREADS = $env:NUMEXPR_NUM_THREADS
    }
    Files = $fileRows
}

$outputRoot = Join-Path $ProjectRoot "outputs\local_environment"
New-Item -ItemType Directory -Force -Path $outputRoot | Out-Null
$reportPath = Join-Path $outputRoot "local_environment_diagnostic.json"
$report | ConvertTo-Json -Depth 8 |
    Set-Content -LiteralPath $reportPath -Encoding UTF8

Write-Host "Project root: $ProjectRoot"
Write-Host "Python: $pythonPath"
Write-Host "Python version: $($version.Output)"
Write-Host "Python 64-bit: $($report.Python64Bit)"
Write-Host "pip: $pip"
Write-Host "pandas: $($pandas.Success) $($pandas.Output)"
Write-Host "numpy: $($numpy.Success) $($numpy.Output)"
Write-Host "project modules: $($project.Success) $($project.Output)"
Write-Host "`nVirtual environments:"
$venvRows | Format-Table -AutoSize
Write-Host "Project files:"
$fileRows | Format-Table -AutoSize
Write-Host "Thread limits:"
$report.ThreadEnvironment | Format-List
Write-Host "Report: $reportPath"
