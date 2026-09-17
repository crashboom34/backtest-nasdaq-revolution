# scripts/autopilot/uninstall_task.ps1 — Retire la tâche planifiée AlphaForgeAutopilot.

$ErrorActionPreference = "Stop"
$TaskName = "AlphaForgeAutopilot"

$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $Existing) {
    Write-Host "Aucune tâche '$TaskName' à retirer."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "Tâche '$TaskName' retirée."
