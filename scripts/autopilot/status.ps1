# scripts/autopilot/status.ps1 — Affiche l'état courant de l'Autopilot (Bootstrap V1, 2026-09-17).

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Environnement virtuel introuvable ($PythonExe)."
    exit 1
}

& $PythonExe -m scripts.autopilot.cli status
exit $LASTEXITCODE
