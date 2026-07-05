param(
    [switch]$SkipInstall,
    [switch]$ForceInstall,
    [switch]$PassThru,
    [switch]$NoPipUpgrade
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

$env:OPENBLAS_NUM_THREADS = "1"
$env:OMP_NUM_THREADS = "1"
$env:MKL_NUM_THREADS = "1"
$env:NUMEXPR_NUM_THREADS = "1"

function Write-Step {
    param([string]$Message)
    Write-Host "[DayTrade Lab] $Message" -ForegroundColor Cyan
}

function Test-Venv {
    param([string]$Root)
    $pythonPath = Join-Path $Root "Scripts\python.exe"
    $activatePath = Join-Path $Root "Scripts\Activate.ps1"
    return (
        (Test-Path -LiteralPath $pythonPath -PathType Leaf) -and
        (Test-Path -LiteralPath $activatePath -PathType Leaf)
    )
}

function Invoke-NativeChecked {
    param(
        [string]$Executable,
        [string[]]$Arguments,
        [string]$Description
    )
    Write-Step $Description
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $nativeOutput = @(& $Executable @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    $nativeOutput | ForEach-Object { Write-Host $_ }
    if ($exitCode -ne 0) {
        if (($nativeOutput -join "`n") -match "WinError 10013") {
            throw (
                "$Description failed because Windows blocked outbound HTTPS " +
                "(WinError 10013). Retry on an authorized network or review " +
                "firewall/EDR rules for $Executable."
            )
        }
        throw "$Description failed with exit code $exitCode"
    }
}

function Test-ProjectImports {
    param([string]$PythonPath)
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $null = & $PythonPath -c (
        "import numpy,pandas,yaml,websockets; import src"
    ) 2>$null
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
    return ($exitCode -eq 0)
}

$venvNames = @(".venv", "venv", "env", ".env")
$selectedRoot = $null
$created = $false
foreach ($name in $venvNames) {
    $candidate = Join-Path $ProjectRoot $name
    if (Test-Venv $candidate) {
        $selectedRoot = $candidate
        Write-Step "Found valid virtual environment: $selectedRoot"
        break
    }
}

if (-not $selectedRoot) {
    $target = Join-Path $ProjectRoot ".venv"
    if ((Test-Path -LiteralPath $target) -and -not (Test-Venv $target)) {
        throw (
            "The path '$target' exists but isn't a valid Windows virtual " +
            "environment. Rename or remove it manually, then rerun this script."
        )
    }
    Write-Step "No valid virtual environment found. Creating .venv..."
    $attempts = [System.Collections.Generic.List[object]]::new()
    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        foreach ($version in @("-3.13", "-3.12", "-3.11", "-3.10", "")) {
            $prefix = @()
            if ($version) {
                $prefix += $version
            }
            $attempts.Add([pscustomobject]@{
                Executable = $pyCommand.Source
                Arguments = @($prefix + @("-m", "venv", $target))
                Label = "py $version"
            })
        }
    }
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        $attempts.Add([pscustomobject]@{
            Executable = $pythonCommand.Source
            Arguments = @("-m", "venv", $target)
            Label = "python"
        })
    }
    if ($attempts.Count -eq 0) {
        throw (
            "Python isn't installed or neither 'py' nor 'python' is in PATH. " +
            "Install 64-bit Python 3.10-3.13 and rerun the script."
        )
    }
    $creationErrors = [System.Collections.Generic.List[string]]::new()
    foreach ($attempt in $attempts) {
        Write-Step "Trying virtual environment creation with $($attempt.Label)..."
        $previousErrorAction = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        & $attempt.Executable @($attempt.Arguments) 2>&1 |
            ForEach-Object { Write-Host $_ }
        $exitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorAction
        if ($exitCode -eq 0 -and (Test-Venv $target)) {
            $selectedRoot = $target
            $created = $true
            break
        }
        $creationErrors.Add("$($attempt.Label): exit=$exitCode")
    }
    if (-not $selectedRoot) {
        throw (
            "Unable to create .venv. Attempts: " +
            ($creationErrors -join "; ") +
            ". Verify that the Python venv component is installed."
        )
    }
    Write-Step "Created virtual environment: $selectedRoot"
}

$venvPython = Join-Path $selectedRoot "Scripts\python.exe"
$activateScript = Join-Path $selectedRoot "Scripts\Activate.ps1"
$pythonVersion = (& $venvPython -c "import platform; print(platform.python_version())").Trim()
$pythonBits = (& $venvPython -c "import struct; print(struct.calcsize('P') * 8)").Trim()
if ($LASTEXITCODE -ne 0) {
    throw "The virtual environment Python couldn't start: $venvPython"
}
if ([int]$pythonBits -ne 64) {
    throw "DayTrade Lab requires 64-bit Python. Detected: $pythonBits-bit."
}
$majorMinor = [Version]("$pythonVersion")
if ($majorMinor.Major -ne 3 -or $majorMinor.Minor -lt 10) {
    throw "Python 3.10 or newer is required. Detected: $pythonVersion"
}
if ($majorMinor.Minor -ge 14) {
    Write-Warning (
        "Python $pythonVersion detected. The project is validated on Python " +
        "3.13; dependency wheels may lag on newer versions."
    )
}

$requirementsPath = Join-Path $ProjectRoot "requirements.txt"
$pyprojectPath = Join-Path $ProjectRoot "pyproject.toml"
$stampRoot = Join-Path $selectedRoot ".daytrade_lab"
$stampPath = Join-Path $stampRoot "dependencies.json"
$dependencyInputs = [System.Collections.Generic.List[string]]::new()
foreach ($path in @($requirementsPath, $pyprojectPath)) {
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        $dependencyInputs.Add("$([IO.Path]::GetFileName($path)):$hash")
    }
}
$dependencyFingerprint = (
    "$pythonVersion|" + ($dependencyInputs -join "|")
)
$installed = $false
$dependenciesReady = $false

if (-not $SkipInstall) {
    $stampMatches = $false
    if (Test-Path -LiteralPath $stampPath -PathType Leaf) {
        try {
            $stamp = Get-Content -LiteralPath $stampPath -Raw |
                ConvertFrom-Json
            $stampMatches = (
                $stamp.fingerprint -eq $dependencyFingerprint
            )
        }
        catch {
            $stampMatches = $false
        }
    }
    $importsReady = Test-ProjectImports $venvPython
    if ($stampMatches -and $importsReady -and -not $ForceInstall) {
        Write-Step "Dependencies already match project files; installation skipped."
        $dependenciesReady = $true
    }
    else {
        if (-not $NoPipUpgrade) {
            Invoke-NativeChecked $venvPython @(
                "-m", "pip", "install", "--upgrade", "pip"
            ) "Upgrading pip"
        }
        if (Test-Path -LiteralPath $requirementsPath -PathType Leaf) {
            Invoke-NativeChecked $venvPython @(
                "-m", "pip", "install", "-r", $requirementsPath
            ) "Installing requirements.txt"
        }
        if (Test-Path -LiteralPath $pyprojectPath -PathType Leaf) {
            Invoke-NativeChecked $venvPython @(
                "-m", "pip", "install", "-e", $ProjectRoot
            ) "Installing editable pyproject package"
        }
        if (
            -not (Test-Path -LiteralPath $requirementsPath) -and
            -not (Test-Path -LiteralPath $pyprojectPath)
        ) {
            throw "Neither requirements.txt nor pyproject.toml exists."
        }
        Invoke-NativeChecked $venvPython @(
            "-c",
            "import numpy,pandas,yaml,websockets; import src; print('imports=OK')"
        ) "Verifying project dependencies"
        New-Item -ItemType Directory -Force -Path $stampRoot | Out-Null
        [ordered]@{
            fingerprint = $dependencyFingerprint
            installed_at_utc = [DateTime]::UtcNow.ToString("o")
            python = $venvPython
        } | ConvertTo-Json |
            Set-Content -LiteralPath $stampPath -Encoding UTF8
        $installed = $true
        $dependenciesReady = $true
    }
}
else {
    Write-Step "Dependency installation skipped by request."
    $dependenciesReady = Test-ProjectImports $venvPython
}

$statusRoot = Join-Path $ProjectRoot "outputs\local_environment"
New-Item -ItemType Directory -Force -Path $statusRoot | Out-Null
$result = [pscustomobject]@{
    ProjectRoot = $ProjectRoot
    VenvRoot = $selectedRoot
    PythonPath = $venvPython
    ActivatePath = $activateScript
    PythonVersion = $pythonVersion
    PythonBits = [int]$pythonBits
    Created = $created
    DependenciesInstalled = $installed
    DependenciesReady = $dependenciesReady
    RequirementsExists = Test-Path -LiteralPath $requirementsPath
    PyprojectExists = Test-Path -LiteralPath $pyprojectPath
    OpenBlasThreads = $env:OPENBLAS_NUM_THREADS
}
$result | ConvertTo-Json |
    Set-Content -LiteralPath (
        Join-Path $statusRoot "venv_status.json"
    ) -Encoding UTF8

Write-Step "Python: $venvPython"
Write-Step "Version: $pythonVersion ($pythonBits-bit)"
Write-Step "Activate (optional): $activateScript"
if ($PassThru) {
    Write-Output $result
}
else {
    $result | Format-List
}
