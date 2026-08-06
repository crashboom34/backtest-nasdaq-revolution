"""
market_data/adapters/single_file_csv.py — Adaptateur MarketDataSource pour un CSV déjà résolu.

Contrairement à LocalCsvMarketDataSource (qui résout un CSV à partir d'un couple asset/timeframe
via path_resolver), cet adaptateur enveloppe un chemin de fichier CSV DÉJÀ CONNU à l'avance :
list_available()/load() ignorent leurs paramètres asset/timeframe et servent toujours le même
fichier fixe.

Utilité (Phase 11, façade de compatibilité) : permettre à optimizer_process.py/optimizer.py de
charger leur `config.data_file` via le port MarketDataSource (donc via
engine.load_data_from_source()) plutôt que d'appeler engine.load_data() directement avec un
chemin brut — sans changer le format de config_used.json ni le comportement observé.

Contrairement à LocalCsvMarketDataSource (qui NORMALISE au schéma canonique via
csv_reading.read_canonical_csv — colonnes restreintes, "volume" synthétisé si absent), cet
adaptateur utilise csv_reading.read_raw_validated_csv() : un passage strictement transparent,
byte-identique à un pd.read_csv() direct. Nécessaire car le vrai nasdaq_3m.csv contient des
colonnes non canoniques (tick_volume, spread) que la normalisation canonique perdrait
silencieusement — voir tests/test_engine_load_data_from_source.py, équivalence vérifiée contre
le vrai fichier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Union

from market_data.csv_reading import read_raw_validated_csv
from market_data.schema import MarketDataResult, MarketDatasetInfo

# Placeholders : cette source ignore asset/timeframe (un seul fichier fixe par instance), mais
# le port MarketDataSource exige que load()/list_available() en manipulent.
PLACEHOLDER_ASSET = "job"
PLACEHOLDER_TIMEFRAME = "job"


class SingleFileCsvMarketDataSource:
    """Adaptateur MarketDataSource pour un unique fichier CSV déjà résolu (chemin fixe)."""

    provider = "single_file_csv"

    def __init__(self, csv_path: Union[str, Path]):
        self._csv_path = Path(csv_path)

    def list_available(self) -> list:
        exists = self._csv_path.is_file()
        return [
            MarketDatasetInfo(
                provider=self.provider,
                asset=PLACEHOLDER_ASSET,
                timeframe=PLACEHOLDER_TIMEFRAME,
                source="data" if exists else "missing",
                exists=exists,
                relative_path=str(self._csv_path) if exists else None,
                message="OK" if exists else f"Fichier introuvable : {self._csv_path}",
            )
        ]

    def load(self, asset: str, timeframe: str) -> MarketDataResult:
        """asset/timeframe sont ignorés : cette source sert toujours le même fichier fixe."""
        info = self.list_available()[0]

        if not self._csv_path.is_file():
            message = f"Fichier introuvable : {self._csv_path}"
            return MarketDataResult(info=info, dataframe=None, ok=False, message=message)

        outcome = read_raw_validated_csv(self._csv_path)
        if not outcome.ok:
            return MarketDataResult(info=info, dataframe=None, ok=False, message=outcome.message)

        return MarketDataResult(info=info, dataframe=outcome.dataframe, ok=True, message="OK")
