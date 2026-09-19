# scripts/autopilot/install_task.ps1 — Installe la tâche planifiée Windows AlphaForgeAutopilot
# (Bootstrap V1, 2026-09-17). N'est PAS exécuté automatiquement par la mission de Bootstrap —
# choix explicite de l'utilisateur, voir .autopilot/README.md.
#
# Tâche PER-USER (ne nécessite pas de droits administrateur tant qu'elle ne s'exécute que quand
# l'utilisateur est connecté — "ne pas contourner" la restriction si des droits admin étaient
# réellement nécessaires, mission §14). Nom spécifique, chemin absolu vérifié, compte utilisateur
# courant, répertoire de travail explicite, une seule instance à la fois.

$ErrorActionPreference = "Stop"
$TaskName = "AlphaForgeAutopilot"
$RepoRoot = (Resolve-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))).Path
$ResumeScript = Join-Path $RepoRoot "scripts\autopilot\resume.ps1"

if (-not (Test-Path $ResumeScript)) {
    Write-Error "Script introuvable : $ResumeScript — vérifier le chemin du dépôt."
    exit 1
}

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "La tâche '$TaskName' existe déjà — exécuter uninstall_task.ps1 d'abord pour la remplacer."
    exit 1
}

$Action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ResumeScript`"" `
    -WorkingDirectory $RepoRoot

# Finalisation "poursuite AlphaForge" (2026-09-19) : un déclenchement SEUL "à la connexion" ne
# rattrape jamais automatiquement une reprise après une pause d'ATTENTE externe (limite de
# dépenses Claude, indisponibilité réseau) — `RestartCount`/`RestartInterval` ci-dessous ne
# couvrent qu'un ÉCHEC/crash du process lui-même, jamais une sortie propre en WAITING_FOR_CLAUDE/
# WAITING_FOR_EXTERNAL_RESOURCE. Bug réel confirmé : une fois la limite de dépenses réinitialisée,
# rien ne relançait l'Autopilot sans intervention manuelle. Second déclencheur : répète
# `resume.ps1` toutes les 30 minutes, indéfiniment (~10 ans, limite pratique du schéma XML de
# Task Scheduler) — sûr par construction : `cmd_resume` réacquiert le verrou fichier avant tout
# travail réel (une instance déjà active fait simplement échouer l'acquisition et sort aussitôt,
# `MultipleInstances=IgnoreNew` ci-dessous ajoute une seconde couche), ne force jamais un
# HUMAN_GATE_REQUIRED (aucun handler n'existe pour lui dans `run_one_step()`, resterait un no-op
# jusqu'à une résolution explicite `autopilot resolve-human-gate`), et ne relève ni ne réinitialise
# jamais un budget/plafond — si la cause externe persiste, la tentative périodique échoue et
# re-parque exactement comme avant, sans effet de bord.
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn
$RepeatingTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) -RepetitionDuration (New-TimeSpan -Days 3650)

$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($LogonTrigger, $RepeatingTrigger) -Settings $Settings `
    -Description "Reprend AlphaForge Autopilot au logon de l'utilisateur courant, puis revérifie automatiquement toutes les 30 minutes (jamais SYSTEM, jamais un autre compte)." `
    -User $env:USERNAME

Write-Host "Tâche '$TaskName' installée (déclenchement : à la connexion de $env:USERNAME)."
Write-Host "Utiliser uninstall_task.ps1 pour la retirer."
