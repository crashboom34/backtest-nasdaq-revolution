"""
ui_data_center.py — Aperçu en lecture seule du "Data Center" (socle local market_data/).

Affiche uniquement des informations déjà calculées par market_data.summary et
market_data.provider_config : catalogue local, statut des timeframes (source / calculable /
en cache), contrôle qualité basique, et statut de configuration des futurs fournisseurs.
N'écrit rien sur disque, ne lance aucun téléchargement, ne modifie aucun CSV existant.

Même convention que ui_components.py : la logique d'assemblage (build_data_center_rows,
build_provider_rows) est séparée du rendu Streamlit, pour rester testable sans dépendance à
Streamlit.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from pathlib import Path
from typing import Union

from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.provider_config import DEFAULT_PROVIDER_SETTINGS_PATH, credential_status
from market_data.summary import DatasetSummary, build_data_center_summary
from ui_components import help_panel, page_header, step_title

# Fournisseurs prévus par la feuille de route du projet (voir CONTEXT.md) — aucun connecteur
# réel n'existe encore pour l'un d'entre eux à ce stade.
KNOWN_FUTURE_PROVIDERS: tuple[str, ...] = (
    "eodhd", "dukascopy", "firstrate", "ig", "binance", "alpaca",
)


def build_data_center_rows(summaries: tuple[DatasetSummary, ...]) -> list[dict]:
    """Transforme des DatasetSummary en lignes affichables. Aucune dépendance à Streamlit."""
    rows: list[dict] = []
    for summary in summaries:
        entry = summary.catalog_entry
        quality = summary.quality

        calculable_count = sum(
            status.status in ("calculable_cached", "calculable_not_cached")
            for status in summary.timeframe_statuses
        )
        cached_count = sum(
            status.status == "calculable_cached" for status in summary.timeframe_statuses
        )

        rows.append(
            {
                "Actif": entry.asset,
                "Timeframe": entry.timeframe,
                "Source": entry.source,
                "Disponible": "Oui" if entry.exists else "Non",
                "Lignes": entry.row_count if entry.row_count is not None else "—",
                "Début": entry.start or "—",
                "Fin": entry.end or "—",
                "UT calculables": calculable_count,
                "UT en cache": cached_count,
                "Qualité (score)": f"{quality.quality_score_pct:.1f} %" if quality else "—",
                "Anomalies": (
                    ", ".join(quality.quality_flags) if quality and quality.quality_flags else "—"
                ),
            }
        )
    return rows


def build_provider_rows(
    providers: tuple[str, ...] = KNOWN_FUTURE_PROVIDERS,
    path: Union[str, Path] = DEFAULT_PROVIDER_SETTINGS_PATH,
) -> list[dict]:
    """Statut de configuration des futurs fournisseurs — ne renvoie jamais la clé elle-même."""
    rows: list[dict] = []
    for provider in providers:
        status = credential_status(provider, path=path)
        rows.append(
            {
                "Fournisseur": provider.upper(),
                "Configuré": "Oui" if status.configured else "Non",
                "Origine": status.source,
                "Détail": status.message,
            }
        )
    return rows


def render_data_center_tab() -> None:
    """Rendu Streamlit en lecture seule du Data Center local."""
    page_header(
        "Data Center — aperçu",
        "Vue d'ensemble locale des données déjà préparées. Lecture seule : rien n'est "
        "téléchargé ni modifié depuis cet écran.",
        "Socle Data Center",
    )
    help_panel(
        "Ce que tu vois ici",
        "Les actifs/timeframes déjà présents dans data/, les unités de temps calculables ou "
        "déjà générées, un contrôle qualité basique, et le statut des futurs fournisseurs de "
        "données (aucun connecteur réel n'est encore branché).",
        "info",
    )

    source = LocalCsvMarketDataSource()
    summaries = build_data_center_summary(source)

    step_title(1, "Jeux de données locaux", "Un jeu de données par actif/timeframe préparé.")
    if rows := build_data_center_rows(summaries):
        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)
    else:
        st.info("Aucun jeu de données détecté pour l'instant.", icon=None)

    step_title(
        2,
        "Futurs fournisseurs de données",
        "Aucun connecteur réel n'est encore branché — voir AI_HANDOFF.md pour l'ordre prévu.",
    )
    st.dataframe(pd.DataFrame(build_provider_rows()), width="stretch", hide_index=True)
    st.caption(
        "Une clé API se configure via la variable d'environnement "
        "BACKTEST_<FOURNISSEUR>_API_KEY, ou dans settings/data_providers.json "
        "(fichier local, jamais versionné)."
    )
