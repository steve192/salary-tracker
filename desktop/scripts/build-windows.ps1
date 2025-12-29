$ErrorActionPreference = "Stop"

$rootDir = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$backendDir = Join-Path $rootDir "desktop\backend"
$buildVenv = Join-Path $backendDir ".venv-build"
$pyenvRoot = Join-Path $backendDir ".pyenv-win"

$pyprojectPath = Join-Path $rootDir "pyproject.toml"
$requiresPython = ">=3.12"
if (Test-Path $pyprojectPath) {
  $line = Get-Content $pyprojectPath | Where-Object { $_ -match '^\s*requires-python\s*=' } | Select-Object -First 1
  if ($line -match '"([^"]+)"') {
    $requiresPython = $Matches[1]
  }
}

$requiredPython = ($requiresPython -replace '>=', '') -split ',' | Select-Object -First 1
$requiredPython = $requiredPython.Trim()
if ([string]::IsNullOrWhiteSpace($requiredPython)) {
  $requiredPython = "3.12"
}

$reqParts = $requiredPython.Split('.')
$reqMajor = [int]$reqParts[0]
$reqMinor = [int]$reqParts[1]

function Test-PythonVersion {
  param([string]$PythonPath)
  & $PythonPath -c "import sys; raise SystemExit(0 if sys.version_info >= ($reqMajor, $reqMinor) else 1)"
  return $LASTEXITCODE -eq 0
}

function Test-PythonShared {
  param([string]$PythonPath)
  & $PythonPath -c "import sysconfig; raise SystemExit(0 if sysconfig.get_config_var('Py_ENABLE_SHARED') else 1)"
  return $LASTEXITCODE -eq 0
}

function Get-PythonFromLauncher {
  param([string]$VersionSpec)
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if (-not $launcher) {
    return $null
  }
  try {
    $path = & py -$VersionSpec -c "import sys; print(sys.executable)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $path) {
      return $path.Trim()
    }
  } catch {
    return $null
  }
  return $null
}

function Install-PyenvWinPython {
  param([string]$VersionPrefix)
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host "Missing git to install pyenv-win."
    exit 1
  }

  if (-not (Test-Path $pyenvRoot)) {
    git clone https://github.com/pyenv-win/pyenv-win $pyenvRoot
  }

  $pyenvBat = Join-Path $pyenvRoot "pyenv-win\bin\pyenv.bat"
  if (-not (Test-Path $pyenvBat)) {
    Write-Host "pyenv-win install failed."
    exit 1
  }

  $env:PYENV = $pyenvRoot
  $env:PYENV_ROOT = $pyenvRoot
  $env:Path = "$pyenvRoot\pyenv-win\bin;$pyenvRoot\pyenv-win\shims;$env:Path"

  $versionsRaw = & $pyenvBat install -l
  $versions = $versionsRaw | ForEach-Object { $_.Trim() } | Where-Object { $_ -match "^$VersionPrefix\.\d+$" }
  $versionObjs = $versions | ForEach-Object { [Version]$_ } | Sort-Object

  if ($versionObjs.Count -gt 0) {
    $latest = $versionObjs[-1].ToString()
  } else {
    $latest = "$VersionPrefix.0"
  }

  & $pyenvBat install $latest
  $candidate = Join-Path $pyenvRoot "pyenv-win\versions\$latest\python.exe"
  if (-not (Test-Path $candidate)) {
    Write-Host "Failed to install Python $latest via pyenv-win."
    exit 1
  }
  return $candidate
}

function Resolve-Python {
  $candidate = $env:PYTHON
  if ($candidate -and (Test-Path $candidate)) {
    if (Test-PythonVersion $candidate -and Test-PythonShared $candidate) {
      return $candidate
    }
  }

  $launcherCandidate = Get-PythonFromLauncher $requiredPython
  if ($launcherCandidate -and (Test-Path $launcherCandidate)) {
    if (Test-PythonVersion $launcherCandidate -and Test-PythonShared $launcherCandidate) {
      return $launcherCandidate
    }
  }

  $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($pythonCmd) {
    $candidate = $pythonCmd.Path
    if (Test-PythonVersion $candidate -and Test-PythonShared $candidate) {
      return $candidate
    }
  }

  return Install-PyenvWinPython $requiredPython
}

$pythonPath = Resolve-Python
if (-not (Test-Path $pythonPath)) {
  Write-Host "Python executable not found."
  exit 1
}

& $pythonPath -m venv $buildVenv
$venvPython = Join-Path $buildVenv "Scripts\python.exe"

& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install "$($rootDir.Path)[desktop-build]"

& $venvPython (Join-Path $rootDir "manage.py") collectstatic --noinput

$env:PYINSTALLER_PROJECT_ROOT = $rootDir.Path
& $venvPython -m PyInstaller (Join-Path $backendDir "backend.spec") `
  --distpath (Join-Path $backendDir "dist") `
  --workpath (Join-Path $backendDir "build") `
  --noconfirm `
  --clean

Set-Location (Join-Path $rootDir "desktop")
npm ci
npm run build -- --win
