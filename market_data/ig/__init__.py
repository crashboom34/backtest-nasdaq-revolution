"""
market_data/ig/ — Connecteur IG, strictement environnement démo, strictement lecture seule.

Endpoints, en-têtes et formats confirmés par recoupement de la documentation officielle IG
Labs (labs.ig.com) et de la bibliothèque open source de référence trading-ig (ig-python), pas
devinés — voir AI_HANDOFF.md pour le détail des sources.

Aucune fonction de trading n'existe dans ce package, structurellement : aucun module ici
n'implémente /positions, /workingorders ou toute autre route d'écriture IG. Ce n'est pas
seulement une convention documentée — ces endpoints ne sont simplement pas câblés.

Aucun appel réseau à l'import. Les identifiants IG peuvent être absents (variables
BACKTEST_IG_*) : ce package reste importable et testable hors ligne dans tous les cas.
"""

from __future__ import annotations
