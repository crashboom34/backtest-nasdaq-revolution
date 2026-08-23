"""
tests/test_ig_normalize.py — Tests de market_data/ig/normalize.py.

Champs bruts confirmés via recoupement documentation officielle IG Labs + bibliothèque de
référence trading-ig (2026-08-06, voir AI_HANDOFF.md) : prices[].{snapshotTime, snapshotTimeUTC,
openPrice: {bid,ask}, highPrice:{bid,ask}, lowPrice:{bid,ask}, closePrice:{bid,ask},
lastTradedVolume}.

`snapshotTimeUTC` — champ source de `time` depuis AF-V-01 (2026-08-23, voir
docs/adr/0017-ig-demo-dataset-snapshot-identity-and-timezone-assumption.md) : `snapshotTime` seul
est ambigu (heure locale non documentée par IG, confusion connue — fil IG Labs "prices API
timezone is messy"), confirmé sur les 4800 enregistrements réels acquis lors d'AF-V-01 Phase A
(écart constant avec `snapshotTimeUTC`, jamais un simple offset supposé). Les fixtures ci-dessous
utilisent volontairement un `snapshotTimeUTC` DIFFÉRENT de `snapshotTime` (jamais un décalage fixe
de 2h, pour ne pas masquer un retour accidentel à un offset codé en dur — voir
test_normalize_price_records_ignores_snapshot_time_entirely_even_with_arbitrary_offset).
"""

from __future__ import annotations

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.errors import IgResponseError
from market_data.ig.normalize import normalize_price_records
from market_data.schema import CANONICAL_COLUMNS

_SAMPLE_PRICES = [
    {
        "snapshotTime": "2026/08/01 02:00:00",
        "snapshotTimeUTC": "2026-08-01T00:00:00",
        "openPrice": {"bid": 100.0, "ask": 100.4},
        "highPrice": {"bid": 105.0, "ask": 105.4},
        "lowPrice": {"bid": 99.0, "ask": 99.4},
        "closePrice": {"bid": 102.0, "ask": 102.4},
        "lastTradedVolume": 150,
    },
    {
        "snapshotTime": "2026/08/02 02:00:00",
        "snapshotTimeUTC": "2026-08-02T00:00:00",
        "openPrice": {"bid": 102.0, "ask": 102.4},
        "highPrice": {"bid": 106.0, "ask": 106.4},
        "lowPrice": {"bid": 101.0, "ask": 101.4},
        "closePrice": {"bid": 104.0, "ask": 104.4},
        "lastTradedVolume": 200,
    },
]


def test_normalize_price_records_produces_canonical_columns():
    df = normalize_price_records(_SAMPLE_PRICES)

    assert set(CANONICAL_COLUMNS).issubset(set(df.columns))
    assert len(df) == 2
    # "time" doit provenir de snapshotTimeUTC (00:00:00), jamais de snapshotTime (02:00:00) —
    # voir docs/adr/0017-... : snapshotTime seul est ambigu, jamais la source canonique.
    assert df["time"].iloc[0] == pd.Timestamp("2026-08-01 00:00:00")
    assert df["time"].dt.tz is None


def test_normalize_price_records_uses_bid_ask_midpoint():
    df = normalize_price_records(_SAMPLE_PRICES)
    row = df.iloc[0]

    assert row["open"] == pytest.approx((100.0 + 100.4) / 2)
    assert row["high"] == pytest.approx((105.0 + 105.4) / 2)
    assert row["low"] == pytest.approx((99.0 + 99.4) / 2)
    assert row["close"] == pytest.approx((102.0 + 102.4) / 2)
    assert row["volume"] == 150


def test_normalize_price_records_keeps_raw_bid_ask_columns():
    df = normalize_price_records(_SAMPLE_PRICES)
    row = df.iloc[0]

    assert row["open_bid"] == 100.0
    assert row["open_ask"] == 100.4
    assert row["close_bid"] == 102.0
    assert row["close_ask"] == 102.4


def test_normalize_price_records_sorts_chronologically():
    reversed_records = list(reversed(_SAMPLE_PRICES))
    df = normalize_price_records(reversed_records)
    assert df["time"].is_monotonic_increasing


def test_normalize_price_records_empty_list_returns_empty_canonical_dataframe():
    df = normalize_price_records([])
    assert set(CANONICAL_COLUMNS).issubset(set(df.columns))
    assert len(df) == 0


def test_normalize_price_records_missing_field_raises_response_error():
    with pytest.raises(IgResponseError):
        normalize_price_records([{"snapshotTimeUTC": "2026-08-01T00:00:00"}])


def test_normalize_price_records_requires_snapshot_time_utc_even_if_snapshot_time_present():
    """snapshotTime seul (sans snapshotTimeUTC) ne suffit plus — voir docs/adr/0017-... : c'est
    précisément le champ ambigu que ce module ne doit plus jamais utiliser comme source de temps."""
    record_without_utc_field = {
        "snapshotTime": "2026/08/01 02:00:00",
        "openPrice": {"bid": 100.0, "ask": 100.4},
        "highPrice": {"bid": 105.0, "ask": 105.4},
        "lowPrice": {"bid": 99.0, "ask": 99.4},
        "closePrice": {"bid": 102.0, "ask": 102.4},
        "lastTradedVolume": 150,
    }
    with pytest.raises(IgResponseError):
        normalize_price_records([record_without_utc_field])


def test_normalize_price_records_ignores_snapshot_time_entirely_even_with_arbitrary_offset():
    """Preuve qu'aucun offset fixe (+1h/+2h/-1h) n'est appliqué nulle part : quel que soit l'écart
    entre snapshotTime et snapshotTimeUTC (ici volontairement un écart absurde de 5h37 pour ne
    ressembler à aucun fuseau réel), "time" doit être EXACTEMENT snapshotTimeUTC parsé, jamais une
    valeur dérivée de snapshotTime par translation d'un offset codé en dur."""
    record = {
        "snapshotTime": "2026/08/01 05:37:00",  # ne doit jamais influencer "time"
        "snapshotTimeUTC": "2026-08-01T00:00:00",
        "openPrice": {"bid": 100.0, "ask": 100.4},
        "highPrice": {"bid": 105.0, "ask": 105.4},
        "lowPrice": {"bid": 99.0, "ask": 99.4},
        "closePrice": {"bid": 102.0, "ask": 102.4},
        "lastTradedVolume": 150,
    }
    df = normalize_price_records([record])
    assert df["time"].iloc[0] == pd.Timestamp("2026-08-01 00:00:00")


def test_normalize_price_records_raises_response_error_if_a_later_record_lacks_utc_field():
    """La validation du champ obligatoire snapshotTimeUTC doit couvrir CHAQUE enregistrement, pas
    seulement le premier (trouvé en revue Spec, 2026-08-23) — sinon un enregistrement ultérieur
    incomplet lève un KeyError brut non maîtrisé au lieu d'un IgResponseError propre."""
    complete_first_record = _SAMPLE_PRICES[0]
    incomplete_second_record = {
        "openPrice": {"bid": 102.0, "ask": 102.4},
        "highPrice": {"bid": 106.0, "ask": 106.4},
        "lowPrice": {"bid": 101.0, "ask": 101.4},
        "closePrice": {"bid": 104.0, "ask": 104.4},
        "lastTradedVolume": 200,
        # snapshotTimeUTC volontairement absent ici, présent sur le premier enregistrement.
    }
    with pytest.raises(IgResponseError):
        normalize_price_records([complete_first_record, incomplete_second_record])


def test_normalize_price_records_does_not_keep_ambiguous_snapshot_time_column():
    """snapshotTime (ambigu) n'est conservé nulle part dans le DataFrame produit — décision
    explicite du contrat (docs/adr/0017-...), pas un oubli : contrairement aux colonnes *_bid/*_ask
    qui portent une information distincte, snapshotTime ne serait qu'une redite ambiguë de "time"."""
    df = normalize_price_records(_SAMPLE_PRICES)
    assert "snapshot_time_local" not in df.columns
    assert "snapshotTime" not in df.columns
