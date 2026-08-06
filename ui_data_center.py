"""
ui_data_center.py — Page Streamlit "Data Center" (socle local + connecteurs EODHD/IG).

Affiche : le catalogue local (market_data.summary), le statut de configuration des
fournisseurs, le connecteur REST EODHD (statut, bouton de test, catalogue des snapshots déjà
téléchargés, journal de synchronisation, espace disque) et le connecteur IG démo (statut,
bouton de test). Lecture seule par défaut : rien n'est téléchargé ni modifié tant que
l'utilisateur ne clique pas explicitement sur un bouton de test.

Ne montre jamais un secret, jamais une valeur masquée de type '****' — uniquement
configuré/absent et, pour IG, "demo (autorisé)" ou un refus générique (jamais la valeur brute
d'un environnement non autorisé, même si ce n'est pas un secret : évite d'afficher "live" en
clair sur cet écran).

Le MCP EODHD est un outil de développement pour Claude Code : il n'est pas accessible depuis
l'application Streamlit en cours d'exécution (processus différent), donc cette page ne peut pas
en vérifier dynamiquement la disponibilité. Une note statique l'explique plutôt que d'afficher un
faux statut.

Même convention que ui_components.py : la logique d'assemblage (build_*) est séparée du rendu
Streamlit (render_data_center_tab), pour rester testable sans dépendance à Streamlit. Les
fonctions run_*_connection_test() sont les seules à faire un appel réseau — jamais au chargement
de la page, uniquement depuis l'intérieur d'un `if st.button(...):`.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from pathlib import Path
from typing import Optional, Union

from market_data.adapters.local_csv import LocalCsvMarketDataSource
from market_data.provider_config import (
    DEFAULT_PROVIDER_SETTINGS_PATH,
    credential_status,
    get_ig_credentials,
    ig_credential_status,
)
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


def build_eodhd_status_row() -> dict:
    """Statut du connecteur REST EODHD — jamais la valeur de la clé."""
    status = credential_status("eodhd")
    return {
        "Connecteur": "REST EODHD",
        "Configuré": "Oui" if status.configured else "Non",
        "Origine": status.source,
        "Détail": status.message,
    }


def build_ig_status_row() -> dict:
    """Statut du connecteur IG démo — jamais api_key/identifier/password, jamais la valeur
    brute de BACKTEST_IG_ENVIRONMENT (seul le fait qu'elle soit "demo" ou non est affiché)."""
    creds = get_ig_credentials()
    env_raw = (creds.environment or "").strip().lower()
    if not env_raw:
        environment_display = "Non configuré"
    elif env_raw == "demo":
        environment_display = "demo (autorisé)"
    else:
        environment_display = "Valeur non autorisée (accès refusé — seul 'demo' est permis)"

    status = ig_credential_status()
    missing = [field for field, origin in status.field_status.items() if origin == "missing"]
    return {
        "Connecteur": "IG (démo)",
        "Configuré": "Oui" if status.configured else "Non",
        "Environnement": environment_display,
        "Champs manquants": ", ".join(missing) if missing else "—",
    }


def build_disk_usage_row() -> Optional[dict]:
    """Espace disque du dossier BACKTEST_DATA_DIR — None si non configuré (pas d'exception)."""
    from market_data.eodhd.errors import EodhdConfigError
    from market_data.eodhd.storage import disk_usage_summary, resolve_data_dir

    try:
        data_dir = resolve_data_dir()
    except EodhdConfigError:
        return None

    summary = disk_usage_summary(data_dir)
    return {
        "Dossier": str(data_dir),
        "Libre": f"{summary.free_gb:.2f} Go",
        "Total": f"{summary.total_gb:.2f} Go",
        "Seuil minimum": f"{summary.min_free_mb / 1024:.1f} Go",
        "Suffisant": "Oui" if summary.sufficient else "Non — libère de l'espace avant un téléchargement",
    }


def build_eodhd_catalog_rows() -> list[dict]:
    """Catalogue des snapshots EODHD déjà stockés localement — liste vide si BACKTEST_DATA_DIR
    n'est pas configuré ou si rien n'a encore été téléchargé (jamais d'exception)."""
    from market_data.eodhd.errors import EodhdConfigError
    from market_data.eodhd.storage import list_normalized_snapshots, resolve_data_dir

    try:
        data_dir = resolve_data_dir()
    except EodhdConfigError:
        return []

    rows: list[dict] = []
    for snapshot in list_normalized_snapshots(data_dir):
        rows.append(
            {
                "Fournisseur": snapshot.provider.upper(),
                "Symbole fournisseur": snapshot.ticker,
                "Actif interne": snapshot.asset,
                "Unité source": snapshot.timeframe,
                "Bourse": snapshot.exchange or "—",
                "Lignes": snapshot.row_count,
                "Début": snapshot.start or "—",
                "Fin": snapshot.end or "—",
                "Fuseau": snapshot.timezone,
                "Qualité": (
                    f"{snapshot.quality_score_pct:.1f} %" if snapshot.quality_score_pct is not None else "—"
                ),
                "Dernière synchro": snapshot.synced_at,
            }
        )
    return rows


def build_sync_status_rows() -> list[dict]:
    """Dernière synchronisation réussie / dernier échec — toujours 2 lignes, jamais d'exception
    même si BACKTEST_DATA_DIR est absent ou si rien n'a encore été synchronisé."""
    from market_data.eodhd.errors import EodhdConfigError
    from market_data.eodhd.storage import last_failed_sync, last_successful_sync, resolve_data_dir

    try:
        data_dir = resolve_data_dir()
    except EodhdConfigError:
        return [
            {"Type": "Dernière synchronisation réussie", "Détail": "BACKTEST_DATA_DIR non configuré"},
            {"Type": "Dernier échec", "Détail": "BACKTEST_DATA_DIR non configuré"},
        ]

    last_ok = last_successful_sync(data_dir)
    last_fail = last_failed_sync(data_dir)
    return [
        {
            "Type": "Dernière synchronisation réussie",
            "Détail": f"{last_ok.ticker} ({last_ok.kind}) — {last_ok.timestamp}" if last_ok else "Aucune pour l'instant",
        },
        {
            "Type": "Dernier échec",
            "Détail": (
                f"{last_fail.ticker} ({last_fail.kind}) — {last_fail.timestamp} : {last_fail.message}"
                if last_fail
                else "Aucun pour l'instant"
            ),
        },
    ]


def build_unified_catalog_rows() -> list[dict]:
    """Catalogue combiné CSV local + EODHD (voir market_data.unified_catalog) — jamais
    d'exception même si BACKTEST_DATA_DIR est absent (la partie CSV local reste affichée)."""
    from market_data.eodhd.errors import EodhdConfigError
    from market_data.eodhd.storage import resolve_data_dir
    from market_data.unified_catalog import build_unified_catalog

    try:
        eodhd_data_dir = resolve_data_dir()
    except EodhdConfigError:
        eodhd_data_dir = None

    entries = build_unified_catalog(
        local_source=LocalCsvMarketDataSource(), eodhd_data_dir=eodhd_data_dir
    )
    return [
        {
            "Fournisseur": entry.provider.upper(),
            "Actif": entry.asset,
            "Timeframe": entry.timeframe,
            "Disponible": "Oui" if entry.exists else "Non",
            "Lignes": entry.row_count if entry.row_count is not None else "—",
            "Début": entry.start or "—",
            "Fin": entry.end or "—",
            "Qualité": f"{entry.quality_score_pct:.1f} %" if entry.quality_score_pct is not None else "—",
            "Détail": entry.extra or "—",
        }
        for entry in entries
    ]


def run_eodhd_connection_test() -> tuple[bool, str]:
    """Effectue un vrai test de connexion EODHD (1 appel API). N'est appelée que depuis un clic
    de bouton explicite — jamais au chargement de la page."""
    from market_data.eodhd.client import EodhdClient
    from market_data.eodhd.config import load_eodhd_config
    from market_data.eodhd.errors import EodhdConfigError, EodhdError

    try:
        config = load_eodhd_config()
    except EodhdConfigError as exc:
        return False, str(exc)

    client = EodhdClient(config=config)
    try:
        result = client.test_connection()
    except EodhdError as exc:
        return False, str(exc)
    return result.ok, result.message


def run_ig_connection_test() -> tuple[bool, str]:
    """Effectue un vrai test de connexion IG démo (connexion + lecture des comptes +
    déconnexion). N'est appelée que depuis un clic de bouton explicite. Refuse toujours un
    environnement non-démo avant le moindre appel réseau (voir market_data.ig.config)."""
    from market_data.ig.client import IgClient
    from market_data.ig.config import load_ig_config
    from market_data.ig.errors import IgConfigError, IgEnvironmentRefusedError, IgError

    try:
        config = load_ig_config()
    except (IgConfigError, IgEnvironmentRefusedError) as exc:
        return False, str(exc)

    client = IgClient(config)
    try:
        result = client.test_connection()
    except IgError as exc:
        return False, str(exc)
    return result.ok, result.message


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
        "EODHD et IG ont un connecteur réel (voir sections suivantes) ; les autres restent "
        "de simples emplacements réservés — voir AI_HANDOFF.md pour l'ordre prévu.",
    )
    st.dataframe(pd.DataFrame(build_provider_rows()), width="stretch", hide_index=True)
    st.caption(
        "Une clé API se configure via la variable d'environnement "
        "BACKTEST_<FOURNISSEUR>_API_KEY, ou dans settings/data_providers.json "
        "(fichier local, jamais versionné)."
    )
    st.caption(
        "MCP EODHD (information de développement uniquement) : outil utilisé par Claude Code "
        "pendant le développement pour valider la documentation et les formats de réponse "
        "EODHD. Il n'est pas accessible depuis cette application en cours d'exécution et n'est "
        "jamais une dépendance du logiciel — le connecteur ci-dessous appelle directement l'API "
        "REST EODHD, avec ou sans Claude Code."
    )

    step_title(
        3,
        "Connecteur REST EODHD",
        "Lecture seule. Le bouton de test effectue un vrai appel réseau minimal (1 appel API).",
    )
    st.dataframe(pd.DataFrame([build_eodhd_status_row()]), width="stretch", hide_index=True)
    if st.button("Tester la connexion EODHD", key="dc_test_eodhd"):
        with st.spinner("Connexion à l'API EODHD..."):
            ok, message = run_eodhd_connection_test()
        if ok:
            st.success(message, icon=None)
        else:
            st.error(message, icon=None)

    st.markdown("**Catalogue EODHD (déjà téléchargé localement)**")
    if eodhd_rows := build_eodhd_catalog_rows():
        st.dataframe(pd.DataFrame(eodhd_rows), width="stretch", hide_index=True)
    else:
        st.info(
            "Aucune donnée EODHD téléchargée localement pour l'instant (ou BACKTEST_DATA_DIR "
            "non configuré).",
            icon=None,
        )
    st.dataframe(pd.DataFrame(build_sync_status_rows()), width="stretch", hide_index=True)
    help_panel(
        "Avant un gros téléchargement",
        "Un historique intraday long se découpe automatiquement en plusieurs fenêtres et peut "
        "consommer un quota important et beaucoup d'espace disque. Vérifie l'espace disque "
        "ci-dessous et commence toujours par une courte période de test.",
        "warning",
    )

    step_title(
        4,
        "Connecteur IG (démo uniquement, lecture seule)",
        "Aucune fonction de trading n'existe dans ce connecteur — impossible de passer un ordre "
        "depuis cette page ou depuis le code.",
    )
    st.dataframe(pd.DataFrame([build_ig_status_row()]), width="stretch", hide_index=True)
    if st.button("Tester la connexion IG (démo)", key="dc_test_ig"):
        with st.spinner("Connexion à l'API IG (démo)..."):
            ok, message = run_ig_connection_test()
        if ok:
            st.success(message, icon=None)
        else:
            st.error(message, icon=None)

    step_title(5, "Stockage local", "Dossier BACKTEST_DATA_DIR.")
    if disk_row := build_disk_usage_row():
        st.dataframe(pd.DataFrame([disk_row]), width="stretch", hide_index=True)
    else:
        st.info("BACKTEST_DATA_DIR n'est pas configuré : aucun stockage local possible pour l'instant.", icon=None)

    step_title(
        6,
        "Catalogue unifié (tous fournisseurs)",
        "Combine les CSV locaux et les données EODHD déjà téléchargées, en une seule vue.",
    )
    if unified_rows := build_unified_catalog_rows():
        st.dataframe(pd.DataFrame(unified_rows), width="stretch", hide_index=True)
    else:
        st.info("Aucune donnée à afficher pour l'instant.", icon=None)
