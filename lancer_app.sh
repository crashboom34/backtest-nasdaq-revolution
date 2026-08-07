#!/usr/bin/env bash
# lancer_app.sh — équivalent Linux de lancer_app.bat (démarrage de l'interface Streamlit).
set -euo pipefail

# Répertoire du script, quel que soit le répertoire courant depuis lequel il est appelé.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
cd "$SCRIPT_DIR"

echo
echo "Backtest Pro - Demarrage sur http://localhost:8501"
echo

"${SCRIPT_DIR}/.venv/bin/python" -m streamlit run app.py \
    --server.port 8501 \
    --browser.gatherUsageStats false

echo
echo "Application arretee."
