"""AF-V-07 E3-B — intégration B3 ↔ B5/B6 : les artefacts `exposure/` d'un dossier de campagne sont une STRUCTURE CONNUE (artefacts informatifs).

Contrat : ADR 0025 23.29.1 (arborescence de `<campaign_dir>/exposure/` : `inventory_<hash>.json`, répertoires `<inventory_id>`, orphelins
`.exposure.tmp.<32 hex>` ; tout autre nom est refusé ; « La construction d'une table de sources par E3-B traite
`<campaign_dir>/exposure/` et ses répertoires d'inventaire comme une structure connue, pour ne pas faire des chaînes d'une autre
campagne des sources inconnues »). Fixtures SYNTHÉTIQUES dans `tmp_path` uniquement.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import gate_v_exposure_interpreters as b3
import gate_v_exposure_store as store
from gate_v_exposure_scan import AuditRoot, EntryClass, scan_audit_roots
from gate_v_final_holdout_protocol import SourceKind
from tests.gate_v_exposure_support import CREATED_AT, LIMITS, W, assemble, interpret, write_json

INVENTORY_ID = "1" * 64
OTHER_ID = "2" * 64
ORPHAN = ".exposure.tmp." + "a" * 32


def make_campaign(tmp_path: Path, name: str = "campaign_x") -> Path:
    directory = tmp_path / name
    write_json(directory / "plan.json", {"campaign_id": name})
    return directory


def interpret_campaign(directory: Path):
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(directory)))
    return b3.interpret_audit_roots((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def touch_json(path: Path) -> None:
    write_json(path, {"anything": "informative"})


def test_a_campaign_with_only_its_anchor_is_complete_control(tmp_path):
    result = interpret_campaign(make_campaign(tmp_path))
    assert result.complete is True and result.findings == ()


def test_a_legitimate_exposure_tree_is_known_structure_not_unknown_sources(tmp_path):
    """RED avant l'ajout additif : `exposure/` était un répertoire INCONNU (donc `UNKNOWN_SOURCE` et inventaire incomplet)."""
    directory = make_campaign(tmp_path)
    publish_source = assemble(interpret(tmp_path / "src"))
    a0 = store.publish_exposure_inventory(directory, publish_source, created_at=CREATED_AT)
    touch_json(directory / "exposure" / INVENTORY_ID / "declaration_0001.json")
    touch_json(directory / "exposure" / INVENTORY_ID / "declaration_0002.json")
    touch_json(directory / "exposure" / INVENTORY_ID / "attestation_0001.json")
    touch_json(directory / "exposure" / OTHER_ID / "declaration_0001.json")
    (directory / "exposure" / ORPHAN).write_bytes(b"partial")
    (directory / "exposure" / INVENTORY_ID / ORPHAN).write_bytes(b"partial")
    assert a0.exists()
    result = interpret_campaign(directory)
    assert result.complete is True and result.incomplete_reasons == ()
    assert not any(f.source_kind is SourceKind.UNKNOWN_SOURCE for f in result.findings) and result.findings == ()


def test_orphans_are_observed_and_recorded_never_read_and_never_a_source(tmp_path):
    directory = make_campaign(tmp_path)
    touch_json(directory / "exposure" / INVENTORY_ID / "declaration_0001.json")
    (directory / "exposure" / ORPHAN).write_bytes(b"partial")
    (directory / "exposure" / INVENTORY_ID / ORPHAN).write_bytes(b"partial")
    result = interpret_campaign(directory)
    (scanned,) = result.scans
    orphans = [o for o in scanned.scan.observations if o.entry_class is EntryClass.TEMP_ORPHAN_FILE]
    assert sorted(o.relative_path for o in orphans) == sorted([f"exposure/{ORPHAN}", f"exposure/{INVENTORY_ID}/{ORPHAN}"])
    assert all(o.anomaly is None and o.value_parsed is False for o in orphans) and result.complete is True


@pytest.mark.parametrize("relative", [
    "exposure/notes.txt",                                   # nom inconnu
    "exposure/declaration_0001.json",                       # ancien chemin (avant 23.29.1) : refusé
    "exposure/attestation.json",                            # ancien chemin : refusé
    "exposure/inventory_" + "A" * 64 + ".json",             # hexadécimal en majuscules
    "exposure/inventory_" + "a" * 63 + ".json",             # hash trop court
    "exposure/inventory_" + "a" * 64 + ".json.bak",
    "exposure/" + "B" * 64 + "/declaration_0001.json",      # répertoire d'inventaire en majuscules
    "exposure/short/declaration_0001.json",                 # nom de répertoire qui n'est pas un inventory_id
    f"exposure/{INVENTORY_ID}/declaration_1.json",          # seq sur un seul chiffre
    f"exposure/{INVENTORY_ID}/declaration_00001.json",      # seq sur cinq chiffres
    f"exposure/{INVENTORY_ID}/attestation_1.json",          # seq d'attestation sur un seul chiffre
    f"exposure/{INVENTORY_ID}/attestation_00001.json",      # seq d'attestation sur cinq chiffres
    f"exposure/{INVENTORY_ID}/declaration_0001.json.tmp",   # temporaire non conforme au motif d'orphelin
    f"exposure/{INVENTORY_ID}/notes.json",
    f"exposure/{INVENTORY_ID}/sub/declaration_0001.json",   # sous-répertoire non prévu
])
def test_anything_outside_the_closed_exposure_table_stays_an_unknown_source_and_makes_the_root_incomplete(tmp_path, relative):
    directory = make_campaign(tmp_path)
    touch_json(directory / relative)
    result = interpret_campaign(directory)
    assert result.complete is False
    assert any(r.startswith(("UNKNOWN_ENTRY:", "SOURCE_ANOMALY:")) for r in result.incomplete_reasons), result.incomplete_reasons
    assert any(f.source_kind is SourceKind.UNKNOWN_SOURCE for f in result.findings)


@pytest.mark.parametrize("relative", [
    f"{ORPHAN}",                                            # orphelin à la racine du dossier de campagne : emplacement non autorisé
    f"exposure/{INVENTORY_ID}/sub/{ORPHAN}",
])
def test_an_orphan_outside_its_exact_locations_is_not_recorded_as_an_orphan(tmp_path, relative):
    directory = make_campaign(tmp_path)
    (directory / relative).parent.mkdir(parents=True, exist_ok=True)
    (directory / relative).write_bytes(b"partial")
    result = interpret_campaign(directory)
    assert result.complete is False


@pytest.mark.parametrize("relative, content", [
    (f"exposure/{INVENTORY_ID}/declaration_0001.json", b"\xff\xfe"),
    (f"exposure/{INVENTORY_ID}/declaration_0001.json", b"[]"),
    (f"exposure/{INVENTORY_ID}/attestation_0001.json", b"[]"),
])
def test_an_unreadable_or_mistyped_informative_exposure_file_makes_the_root_incomplete(tmp_path, relative, content):
    directory = make_campaign(tmp_path)
    (directory / relative).parent.mkdir(parents=True, exist_ok=True)
    (directory / relative).write_bytes(content)
    result = interpret_campaign(directory)
    assert result.complete is False and any(r.startswith("INFORMATIVE_UNRESOLVED:") for r in result.incomplete_reasons)
    assert not any(f.source_kind is SourceKind.UNKNOWN_SOURCE for f in result.findings)     # informatif : ni finding ni source exposante


def test_exposure_files_never_become_exposure_findings_and_do_not_widen_completeness(tmp_path):
    """Un fichier légitime d'`exposure/` est informatif : il ne crée aucune exposition, et un fichier absent de la table ne la masque pas."""
    directory = make_campaign(tmp_path)
    touch_json(directory / "exposure" / INVENTORY_ID / "declaration_0001.json")
    (directory / "stray.json").write_bytes(b"{}")
    result = interpret_campaign(directory)
    assert result.complete is False and [f.source_kind for f in result.findings] == [SourceKind.UNKNOWN_SOURCE]


# ── Rétrocompatibilité : les autres dispositions et les règles existantes sont inchangées ─────────────────────────────

PINNED_DIGESTS = {
    b3.RootLayout.RESULTS: "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960",
    b3.RootLayout.SPLIT_PLAN_DIR: "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29",
}


@pytest.mark.parametrize("layout", sorted(PINNED_DIGESTS, key=lambda item: item.value))
def test_the_other_layouts_keep_exactly_their_published_rules_digest(tmp_path, layout):
    """Valeurs relevées sur B3 publié (commit 41fe58d) AVANT l'ajout : une table inchangée garde son `rules_digest`."""
    root = tmp_path / layout.value
    (root / "x").mkdir(parents=True)
    scan = scan_audit_roots((AuditRoot("r", str(root)),), b3.source_rules(layout), LIMITS)
    assert scan.rules_digest == PINNED_DIGESTS[layout]


PUBLISHED_V2_DIGESTS = {                                     # mesurés sur `git archive 41fe58d` (B3 v2 publié), source indépendante
    b3.RootLayout.RESULTS: "9014a865e7c5c4fea0ec7fc4cbcd3e8d76357a51693c339981e50f523ae51960",
    b3.RootLayout.CAMPAIGN_DIR: "cb94f97f1b2c53f8839f90547b3ad619e5a3a64dacfb857071554d329a6a6fa7",
    b3.RootLayout.SPLIT_PLAN_DIR: "e98082afc0482e2afdce61884f0da5f264a943defd666ca4aedd8b75ec217f29",
}


def test_b3_is_version_3_since_the_exposure_tree_and_the_orphan_a0_rule():
    """D3 (ADR 0025 23.31.2) : un changement d'interprétation change la version ; la v2 reste un état publié distinct."""
    assert b3.B3_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v3"


def known_rules_digests(version: str) -> dict:
    return {layout: digest for known, layout, digest in b3.B3_RULES_DIGESTS if known == version}


def test_the_known_b3_versions_pin_the_rules_digest_of_each_layout_and_differ_only_on_the_campaign_table():
    assert b3.KNOWN_B3_VERSIONS == ("gate_v_exposure_interpreters_v2", "gate_v_exposure_interpreters_v3")
    assert type(b3.B3_RULES_DIGESTS) is tuple and {version for version, _, _ in b3.B3_RULES_DIGESTS} == set(b3.KNOWN_B3_VERSIONS)
    assert len({(version, layout) for version, layout, _ in b3.B3_RULES_DIGESTS}) == len(b3.B3_RULES_DIGESTS)   # une valeur par couple
    assert known_rules_digests("gate_v_exposure_interpreters_v2") == PUBLISHED_V2_DIGESTS
    current = known_rules_digests(b3.B3_SEMANTICS_VERSION)
    assert set(current) == set(b3.RootLayout)
    assert {layout for layout in current if current[layout] != PUBLISHED_V2_DIGESTS[layout]} == {b3.RootLayout.CAMPAIGN_DIR}


def test_the_v2_campaign_digest_is_derived_from_the_two_published_campaign_rules_alone(tmp_path):
    """Dérivation INDÉPENDANTE des constantes : la table CAMPAIGN_DIR de B3 v2 (41fe58d) était exactement l'ancre et le Claim, règles
    conservées inchangées et en tête en v3 (test ci-dessous) ; un scan réel de ces deux règles seules redonne le digest v2 enregistré."""
    root = tmp_path / "camp"
    (root / "x").mkdir(parents=True)
    published = b3.source_rules(b3.RootLayout.CAMPAIGN_DIR)[:2]
    digest = scan_audit_roots((AuditRoot("r", str(root)),), published, LIMITS).rules_digest
    assert digest == known_rules_digests("gate_v_exposure_interpreters_v2")[b3.RootLayout.CAMPAIGN_DIR] == PUBLISHED_V2_DIGESTS[b3.RootLayout.CAMPAIGN_DIR]


@pytest.mark.parametrize("layout", list(b3.RootLayout), ids=lambda layout: layout.value)
def test_the_current_registry_entry_is_the_digest_that_a_real_scan_of_the_current_table_yields(tmp_path, layout):
    root = tmp_path / layout.value
    (root / "x").mkdir(parents=True)
    scan = scan_audit_roots((AuditRoot("r", str(root)),), b3.source_rules(layout), LIMITS)
    assert known_rules_digests(b3.B3_SEMANTICS_VERSION)[layout] == scan.rules_digest


def test_the_two_published_campaign_rules_are_kept_unchanged_and_first(tmp_path):
    rules = b3.source_rules(b3.RootLayout.CAMPAIGN_DIR)
    assert [r.segments for r in rules[:2]] == [("plan.json",), ("final_holdout_access_claim.json",)]
    assert [(r.entry_class, r.tag) for r in rules[:2]] == [(EntryClass.INFORMATIVE_JSON, b3.TAG_CAMPAIGN_PLAN),
                                                          (EntryClass.EXPOSING_JSON, b3.TAG_CAMPAIGN_CLAIM)]


# ── A0 illisible non épinglé = orphelin consigné (ADR 23.29.1), jamais une incomplétude du scan ─────────────────────────

A0_NAME = "exposure/inventory_" + "a" * 64 + ".json"
UNREADABLE_A0_CONTENTS = [
    pytest.param(b"{", id="truncated"),
    pytest.param(b"\xff\xfe", id="not_utf8"),
    pytest.param(b"[]", id="not_an_object"),
    pytest.param(b'{"a": 1, "a": 2}', id="duplicate_key"),
    pytest.param(b"\xef\xbb\xbf{}", id="bom"),
    pytest.param(b'{"a": NaN}', id="non_finite"),
    pytest.param(b'{"a": "\\ud800"}', id="lone_surrogate"),
    pytest.param(b"[" * 64 + b"]" * 64, id="too_deep"),
    pytest.param(b'{"a": "' + b"x" * 1_100_000 + b'"}', id="too_large_for_the_scan_limit"),
]


def a0_observations(result) -> list:
    return [o for item in result.scans for o in item.scan.observations if o.rule_tag == b3.TAG_EXPOSURE_INVENTORY]


@pytest.mark.parametrize("content", UNREADABLE_A0_CONTENTS)
def test_an_unreadable_a0_is_a_recorded_orphan_and_does_not_make_the_scan_incomplete(tmp_path, content):
    directory = make_campaign(tmp_path)
    (directory / A0_NAME).parent.mkdir(parents=True, exist_ok=True)
    (directory / A0_NAME).write_bytes(content)
    result = interpret_campaign(directory)
    assert result.complete is True and result.incomplete_reasons == () and result.findings == ()
    (observation,) = a0_observations(result)                                   # consigné : l'observation et son anomalie restent visibles
    assert observation.anomaly is not None and observation.relative_path == A0_NAME


def test_an_orphan_a0_changes_no_scientific_identity(tmp_path):
    clean = make_campaign(tmp_path / "clean")
    dirty = make_campaign(tmp_path / "dirty")
    (dirty / A0_NAME).parent.mkdir(parents=True, exist_ok=True)
    (dirty / A0_NAME).write_bytes(b"{")
    first, second = assemble(interpret_campaign(clean)), assemble(interpret_campaign(dirty))
    assert (first.inventory_id, first.inventory_content_digest) == (second.inventory_id, second.inventory_content_digest)


def test_the_orphan_exception_never_hides_a_real_unknown_source(tmp_path):
    directory = make_campaign(tmp_path)
    (directory / A0_NAME).parent.mkdir(parents=True, exist_ok=True)
    (directory / A0_NAME).write_bytes(b"{")
    (directory / "stray.json").write_bytes(b"{}")
    result = interpret_campaign(directory)
    assert result.complete is False and any(f.source_kind is SourceKind.UNKNOWN_SOURCE for f in result.findings)


def test_a_directory_named_like_an_a0_is_not_an_orphan_and_stays_unresolved(tmp_path):
    directory = make_campaign(tmp_path)
    (directory / A0_NAME).mkdir(parents=True)
    result = interpret_campaign(directory)
    assert result.complete is False


# NB : le test « le scanner (B3) et le chargeur de lignée (B6) s'accordent sur un A0 illisible » vit dans
# `tests/test_gate_v_exposure_attestation_phases.py` (il importe B6) afin que le commit de B5 reste autonome.
