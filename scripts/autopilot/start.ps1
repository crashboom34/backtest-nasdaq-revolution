# scripts/autopilot/start.ps1 — Démarre le superviseur Autopilot (Bootstrap V1, 2026-09-17).
# Voir .autopilot/README.md avant la première utilisation réelle.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Environnement virtuel introuvable ($PythonExe) — créer .venv avant de démarrer l'Autopilot."
    exit 1
}

& $PythonExe -m scripts.autopilot.cli start
exit $LASTEXITCODE
