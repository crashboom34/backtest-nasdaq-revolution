# scripts/autopilot/stop.ps1 — Arrête proprement l'Autopilot (libère le verrou, Bootstrap V1).

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Environnement virtuel introuvable ($PythonExe)."
    exit 1
}

& $PythonExe -m scripts.autopilot.cli stop
exit $LASTEXITCODE
