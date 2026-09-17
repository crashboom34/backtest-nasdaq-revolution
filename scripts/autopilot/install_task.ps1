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

$Trigger = New-ScheduledTaskTrigger -AtLogOn

$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Reprend AlphaForge Autopilot au logon de l'utilisateur courant (jamais SYSTEM, jamais un autre compte)." `
    -User $env:USERNAME

Write-Host "Tâche '$TaskName' installée (déclenchement : à la connexion de $env:USERNAME)."
Write-Host "Utiliser uninstall_task.ps1 pour la retirer."
