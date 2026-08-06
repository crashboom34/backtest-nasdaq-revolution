"""
market_data/eodhd/ — Connecteur REST EODHD (Phase 4 du Data Center).

Package séparé en petits modules à responsabilité unique :
  - errors.py     : hiérarchie d'exceptions du fournisseur (jamais de secret dans un message)
  - config.py     : résolution de la configuration (clé API, timeouts, retries...)
  - http_client.py: client HTTP bas niveau (timeouts, retry/backoff, mapping des codes HTTP)
  - windowing.py  : découpage des téléchargements intraday selon les fenêtres autorisées EODHD
  - normalize.py  : conversion des réponses brutes EODHD vers le schéma canonique
  - storage.py    : stockage local (brut immuable + normalisé Parquet) sous BACKTEST_DATA_DIR
  - client.py     : EodhdClient — assemble tout, expose les fonctions publiques du connecteur

Aucun appel réseau n'est effectué à l'import de ce package ou de ses sous-modules.
"""

from __future__ import annotations
