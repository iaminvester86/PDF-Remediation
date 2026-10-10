# Install PDF Remediation with all engines on Windows (PowerShell 5+).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# Installs: the application, Python OCR (RapidOCR), the OpenDataLoader structure
# engine, and the veraPDF validator (downloaded from Maven Central with pinned
# SHA-256 checksums). Java 11+ is needed for the two Java engines.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$venv = if ($env:VENV) { $env:VENV } else { ".venv" }

$py = Get-Command py -ErrorAction SilentlyContinue
$python = if ($py) { "py" } else { "python" }
$pyArgs = if ($py) { @("-3") } else { @() }
& $python @pyArgs -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 or newer is required." }

Write-Host "==> Creating virtual environment in $venv"
& $python @pyArgs -m venv $venv
$vpy = Join-Path $venv "Scripts\python.exe"
& $vpy -m pip install --quiet --upgrade pip
Write-Host "==> Installing PDF Remediation with OCR and OpenDataLoader"
& $vpy -m pip install --quiet -e ".[all]"

$pdfrem = Join-Path $venv "Scripts\pdfrem.exe"
if (Get-Command java -ErrorAction SilentlyContinue) {
    Write-Host "==> Installing the veraPDF validator"
    & $pdfrem install-engines
} else {
    Write-Warning "Java was not found. Install Java 17 or 21 (for example Eclipse Temurin: https://adoptium.net), then run: $pdfrem install-engines"
}

Write-Host ""
& $pdfrem doctor
Write-Host ""
Write-Host "Start the web app with:  $pdfrem serve"
