Param(
    [string]$VenvPath = ".venv",
    [string]$Requirements = "backend\requirements-agentic.txt"
)

Write-Host "[setup] Creating unified venv at $VenvPath"

function Get-PythonLauncher {
    if (Get-Command py -ErrorAction SilentlyContinue) { return "py -3" }
    if (Get-Command python -ErrorAction SilentlyContinue) { return "python" }
    throw "Python not found in PATH. Install Python 3.10+ first."
}

$python = Get-PythonLauncher

if (Test-Path $VenvPath) {
    Write-Host "[setup] Existing venv found at $VenvPath (will reuse)"
} else {
    Write-Host "[setup] Creating venv..."
    & $python -m venv $VenvPath
}

$venvPy = Join-Path $VenvPath "Scripts/python.exe"
if (-Not (Test-Path $venvPy)) {
    throw "Virtual env python not found at $venvPy"
}

Write-Host "[setup] Upgrading pip/setuptools/wheel"
& $venvPy -m pip install -U pip setuptools wheel

Write-Host "[setup] Installing requirements from $Requirements"
& $venvPy -m pip install -r $Requirements

Write-Host "`n[ok] Unified environment ready at $VenvPath"
Write-Host "Activate it in this session with:`n  .\\$VenvPath\\Scripts\\Activate.ps1"
Write-Host "Run backend:`n  python -m uvicorn backend.apps.coordinator.main:app --reload"
