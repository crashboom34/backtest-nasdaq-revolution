# scripts/autopilot/resume.ps1 — Reprend l'Autopilot après arrêt/crash/redémarrage (Bootstrap V1).
# Bootstrap V1 : `cli.py cmd_resume` est un simple alias de `cmd_start` — il acquiert le verrou et
# affiche un statut, il n'appelle PAS encore `run_one_step()`/`run_until()` (la boucle réelle n'est
# pas câblée dans cette mission, voir .autopilot/README.md "Limites connues"). La logique
# d'idempotence/reprise (relire l'état persisté et ne pas refaire les étapes déjà terminées) existe
# et est testée dans scripts/autopilot/supervisor.py, mais seulement exercée via des doublures.

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $RepoRoot

$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonExe)) {
    Write-Error "Environnement virtuel introuvable ($PythonExe)."
    exit 1
}

& $PythonExe -m scripts.autopilot.cli resume
exit $LASTEXITCODE
