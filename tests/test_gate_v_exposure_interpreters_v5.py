"""AF-V-07 B3 v5-A — tables FERMÉES des artefacts K1 (sorties Walk-Forward hachées, preuves de run, orphelins de publication).

Lot autorisé par l'utilisateur (2026-10-25) : reconnaissance structurelle uniquement. R9 et D1-D9 restent PROPOSED dans leur ensemble ; aucun nouveau
SourceKind d'E3-A ; aucun verdict d'absence d'exposition ; aucun nouveau FRESH. Fixtures SYNTHÉTIQUES dans `tmp_path` : aucune donnée de marché,
aucun FINAL_HOLDOUT. Les valeurs attendues (digests, chemins) sont des littéraux ou un oracle écrit dans ce fichier, jamais le code testé.

Le module B3 historique (`gate_v_exposure_interpreters`, v4) n'est PAS modifié : v5 est un module frère, activé explicitement.
"""

from __future__ import annotations

import hashlib
import json
import re

import gate_v_exposure_interpreters as b3
import gate_v_exposure_interpreters_v5 as v5
import gate_v_exposure_scan as scan

V4 = "gate_v_exposure_interpreters_v4"
CAMPAIGN = b3.RootLayout.CAMPAIGN_DIR
ORPHAN = scan.EntryClass.TEMP_ORPHAN_FILE


def oracle_digest(rules) -> str:
    """Oracle indépendant de `gate_v_exposure_scan._rules_digest` (sérialisation canonique, ordre des règles indifférent)."""
    lines = sorted(json.dumps({"segments": [s if type(s) is str else {"regex": s.regex} for s in r.segments], "entry_class": r.entry_class.value,
                               "expected_json": r.expected_json.value if r.expected_json else None, "tag": r.tag},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=True) for r in rules)
    return hashlib.sha256("\n".join(lines).encode("ascii")).hexdigest()


def shape(rule) -> tuple:
    return (tuple(s if type(s) is str else s.regex for s in rule.segments), rule.entry_class.value, rule.tag)


# Forme d'un orphelin de `save_atomic` (`<cible>.<uuid4 hex>.tmp`), écrite ici à la main : littéral échappé ou groupe enveloppé.
SUFFIX = r"\.[0-9a-f]{32}\.tmp"


def orphan_of_literal(name: str) -> str:
    return re.escape(name) + SUFFIX


def orphan_of_pattern(regex: str) -> str:
    return "(?:" + regex + ")" + SUFFIX


FOLD = "fold_[0-9]{3}"
WF = ("walk_forward",)
CKPT = ("walk_forward", ".gate_v_checkpoints_v1")
RUN_DIR_ANY = "gate_v_v2_[0-9a-f]{64}_(walk_forward|monte_carlo|parameter_stability_fold_[0-9]{3})"
RUN_DIR_WF = "gate_v_v2_[0-9a-f]{64}_walk_forward"


def expected_additions() -> set:
    """AJOUTS de v5 à la table de campagne v4, écrits d'après les producteurs réels (`walk_forward.persist_walk_forward_run`, la capture V1
    `.gate_v_checkpoints_v1`, `gate_v_campaign._run_walk_forward_phase`) ; `train_progress.csv` (reprise héritée, supprimé en fin de fold) est EXCLU."""
    out = {(WF, "STRUCTURAL_DIRECTORY", "wf.output.dir"), (WF + ("folds",), "STRUCTURAL_DIRECTORY", "wf.output.folds"),
           (WF + ("folds", FOLD), "STRUCTURAL_DIRECTORY", "wf.output.fold"), (CKPT, "STRUCTURAL_DIRECTORY", "wf.checkpoint.dir"),
           (CKPT + ("folds",), "STRUCTURAL_DIRECTORY", "wf.checkpoint.folds")}
    for name, tag in (("manifest.json", "wf.output.manifest"), ("state.json", "wf.output.state"), ("aggregate.json", "wf.output.aggregate")):
        out.add((WF + (name,), "HASHED_FILE", tag))
        out.add((WF + (orphan_of_literal(name),), "TEMP_ORPHAN_FILE", "wf.output.orphan"))
    for name in ("definition.json", "selection.json", "test_result.json"):
        out.add((WF + ("folds", FOLD, name), "HASHED_FILE", "wf.output.fold_json"))
        out.add((WF + ("folds", FOLD, orphan_of_literal(name)), "TEMP_ORPHAN_FILE", "wf.output.orphan"))
    for name in ("train_candidates.csv", "oos_trades.csv", "oos_equity.csv"):
        out.add((WF + ("folds", FOLD, name), "HASHED_FILE", "wf.output.fold_csv"))
    out.add((CKPT + ("manifest.json",), "HASHED_FILE", "wf.checkpoint.manifest"))
    out.add((CKPT + (orphan_of_literal("manifest.json"),), "TEMP_ORPHAN_FILE", "wf.output.orphan"))
    out.add((CKPT + ("folds", FOLD + r"\.json"), "HASHED_FILE", "wf.checkpoint.fold"))
    out.add((CKPT + ("folds", orphan_of_pattern(FOLD + r"\.json")), "TEMP_ORPHAN_FILE", "wf.output.orphan"))
    out.add((("validations", RUN_DIR_WF, "run_data_coverage.json"), "EXPOSING_JSON", "validation.coverage"))
    out.add((("validations", RUN_DIR_WF, r"run_session_[0-9]{4}\.json"), "EXPOSING_JSON", "validation.session"))
    out.add((("validations", RUN_DIR_WF, "run_seal.json"), "EXPOSING_JSON", "validation.seal"))
    out.add((("validations", RUN_DIR_ANY, orphan_of_literal("validation_run.json")), "TEMP_ORPHAN_FILE", "validation.run.orphan"))
    return out


# ══ B3-v5A-1 : version, tables, digests ═══════════════════════════════════════════════════════════════════════════════════════════
def test_v5_is_a_distinct_explicit_version_and_the_historical_module_keeps_v4_as_its_only_current_version():
    assert v5.B3_V5_SEMANTICS_VERSION == "gate_v_exposure_interpreters_v5"
    assert b3.B3_SEMANTICS_VERSION == V4 and V4 in b3.KNOWN_B3_VERSIONS and v5.B3_V5_SEMANTICS_VERSION not in b3.KNOWN_B3_VERSIONS
    assert len(b3.B3_RULES_DIGESTS) == 9 and v5.B3_V5_SEMANTICS_VERSION not in {version for version, _, _ in b3.B3_RULES_DIGESTS}


def test_results_and_split_plan_tables_are_the_very_same_objects_as_v4_and_the_campaign_table_extends_v4_without_changing_it():
    assert v5.source_rules_v5(b3.RootLayout.RESULTS) is b3.source_rules(b3.RootLayout.RESULTS)
    assert v5.source_rules_v5(b3.RootLayout.SPLIT_PLAN_DIR) is b3.source_rules(b3.RootLayout.SPLIT_PLAN_DIR)
    v4_rules, v5_rules = b3.source_rules(CAMPAIGN), v5.source_rules_v5(CAMPAIGN)
    assert v5_rules[:len(v4_rules)] == v4_rules and len(v5_rules) > len(v4_rules)             # v4 en tête, même ordre, inchangée


def test_no_historical_table_has_a_hashed_rule_or_a_run_orphan_rule():
    for layout in b3.RootLayout:
        assert not any(rule.entry_class.is_hashed for rule in b3.source_rules(layout))
    assert {shape(r) for r in b3.source_rules(CAMPAIGN) if r.entry_class is ORPHAN} == {
        (("exposure", scan.EXPOSURE_TEMP_ORPHAN_PATTERN), "TEMP_ORPHAN_FILE", "campaign.exposure.orphan"),
        (("exposure", "[0-9a-f]{64}", scan.EXPOSURE_TEMP_ORPHAN_PATTERN), "TEMP_ORPHAN_FILE", "campaign.exposure.chain_orphan")}


def test_the_campaign_table_of_v5_adds_exactly_the_audited_rules_and_nothing_else():
    added = {shape(rule) for rule in v5.source_rules_v5(CAMPAIGN)[len(b3.source_rules(CAMPAIGN)):]}
    assert added == expected_additions()
    assert len(added) == len(v5.source_rules_v5(CAMPAIGN)) - len(b3.source_rules(CAMPAIGN))      # aucun doublon


def test_only_the_campaign_table_of_v5_carries_hashed_rules_and_each_one_has_no_json_expectation():
    for layout in b3.RootLayout:
        hashed = [rule for rule in v5.source_rules_v5(layout) if rule.entry_class.is_hashed]
        assert bool(hashed) == (layout is CAMPAIGN)
        assert all(rule.expected_json is None for rule in hashed)


def test_v5_digests_are_computed_by_the_b2_algorithm_and_historical_digests_are_unchanged():
    assert type(v5.B3_V5_RULES_DIGESTS) is tuple and len(v5.B3_V5_RULES_DIGESTS) == 3
    by_layout = {layout: digest for version, layout, digest in v5.B3_V5_RULES_DIGESTS if version == v5.B3_V5_SEMANTICS_VERSION}
    assert set(by_layout) == set(b3.RootLayout)
    historical = {layout: digest for version, layout, digest in b3.B3_RULES_DIGESTS if version == V4}
    for layout in b3.RootLayout:
        rules = v5.source_rules_v5(layout)
        assert by_layout[layout] == scan._rules_digest(rules) == oracle_digest(rules)
    assert by_layout[b3.RootLayout.RESULTS] == historical[b3.RootLayout.RESULTS]
    assert by_layout[b3.RootLayout.SPLIT_PLAN_DIR] == historical[b3.RootLayout.SPLIT_PLAN_DIR]
    assert by_layout[CAMPAIGN] != historical[CAMPAIGN]
    assert by_layout[CAMPAIGN] == "aa389aca9e29052ce9812c766f99abaf95a2bb656a3e82fcff17ab041d4a10af"       # littéral gelé, vecteur recalculable (note B3 v5-A)
    assert scan._rules_digest(b3.source_rules(CAMPAIGN)) == historical[CAMPAIGN] == "9c05f8b068ac86d321c0d9889df0f3c0f1e015fdd8b17d208479554b1badb43b"


# ══ Fixtures : arbres de campagne synthétiques aux formes des producteurs réels ════════════════════════════════════════════════════
import copy  # noqa: E402
import os  # noqa: E402

import pytest  # noqa: E402

import gate_v_exposure_inventory as b4  # noqa: E402
import gate_v_frame_digest as fd  # noqa: E402
import gate_v_run_evidence_models as ev  # noqa: E402
from gate_v_exposure_scan import AuditRoot, ExposureScanRefusal, HashLimits, ScanHooks, StructuralFailure  # noqa: E402
from gate_v_final_holdout_protocol import (  # noqa: E402
    ChronologyFacts, ClassificationInput, DeclarationSet, ExposureClass, OverlapVerdict, OwnCampaignContext, OwnRecordStage, SourceKind,
    SourceStatus, TimeProofFact, TimeProofStatus, UnresolvedCause, build_exposure_declaration, classify_exposure,
)
from tests.gate_v_exposure_support import LIMITS, W, write_json  # noqa: E402

CID = "gate_v_v2_" + "cd" * 32
RUN_WF_ID, RUN_MC_ID, RUN_PS_ID = f"{CID}_walk_forward", f"{CID}_monte_carlo", f"{CID}_parameter_stability_fold_000"
HL = HashLimits(max_hashed_file_bytes=65_536, max_total_hashed_bytes=2_000_000, max_hashed_files=200)
CSV = ("time,open,high,low,close,tick_volume,spread\n2025-12-31 23:51:00,100.10,100.30,100.00,100.20,7,180\n"
       "2025-12-31 23:54:00,100.20,100.40,100.10,100.30,9,180\n2025-12-31 23:57:00,100.30,100.50,100.20,100.40,11,180\n")
RUNTIME = {"numpy": "2.2.6", "pandas": "3.0.3", "python": "3.13.7"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_record(run_id: str, validation_type: str = "walk_forward") -> dict:
    return {"validation_run_id": run_id, "research_run_id": "r", "split_plan_id": "s", "dataset_snapshot_id": "S0", "validation_type": validation_type,
            "strategy_name": "st", "strategy_params": {}, "evidence": {}, "status": "completed", "completed_at": "2025-12-01T00:00:00+00:00"}


def evidence_models(run_id: str = RUN_WF_ID):
    coverage = ev.RunDataCoverage.from_s0_facts(run_id, fd.compute_s0_frame_facts(CSV.encode(), 180), RUNTIME)
    session = ev.RunSession.open_for(coverage, 1, coverage.frame_sha256, coverage.row_count, False)
    seal = ev.RunSeal.for_walk_forward(coverage, [session], "9a" * 32, [("walk_forward/manifest.json", "41" * 32, 8)], coverage.frame_sha256, False)
    return coverage, session, seal


def evidence_files(run_id: str = RUN_WF_ID) -> dict:
    coverage, session, seal = evidence_models(run_id)
    base = f"validations/{run_id}"
    return {f"{base}/run_data_coverage.json": coverage.to_bytes(), f"{base}/run_session_0001.json": session.to_bytes(), f"{base}/run_seal.json": seal.to_bytes()}


FOLDS = ("fold_000", "fold_001")


def wf_outputs() -> dict:
    """Arbre `walk_forward/` aux chemins réellement produits ; chaque fichier a un contenu distinct (hash distinct)."""
    paths = ["walk_forward/manifest.json", "walk_forward/state.json", "walk_forward/aggregate.json", "walk_forward/.gate_v_checkpoints_v1/manifest.json"]
    for fold in FOLDS:
        paths += [f"walk_forward/folds/{fold}/{name}" for name in ("definition.json", "selection.json", "test_result.json", "train_candidates.csv",
                                                                     "oos_trades.csv", "oos_equity.csv")]
        paths.append(f"walk_forward/.gate_v_checkpoints_v1/folds/{fold}.json")
    return {path: f"content of {path}\n".encode() for path in paths}


def build(tmp_path, files: dict = None, *, name: str = CID, run_record_for=RUN_WF_ID):
    """Dossier de campagne : `plan.json` (ancre), le `validation_run.json` du run WF (sauf `run_record_for=None`) puis `files` (bytes bruts)."""
    directory = tmp_path / name
    write_json(directory / "plan.json", {"campaign_id": name})
    if run_record_for is not None:
        write_json(directory / "validations" / run_record_for / "validation_run.json", run_record(run_record_for))
    for relative, data in (files or {}).items():
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return directory


def interpret_v5(directory, *, hl=HL, label="camp", hooks=None, limits=LIMITS):
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot(label, str(directory)))
    return v5.interpret_audit_roots_v5((root,), limits, hash_limits=hl, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1], hooks=hooks)


def finding_of(result, source_id):
    (match,) = [f for f in result.findings if f.source_id == source_id]
    return match


def reasons_with(result, code):
    return [reason for reason in result.incomplete_reasons if reason.startswith(code + ":")]


def classification_of(interpretation):
    assembly = b4.assemble_exposure_inventory(interpretation, registry=b4.RegistryView("reg", None, ()), accounting=b4.AccountingViews(),
                                              own_context=OwnCampaignContext("campaign_current", OwnRecordStage.NO_OWN_RECORDS), derived_root_labels=())
    declaration = build_exposure_declaration(declaration_seq=1, declarant="Mira", inventory_id=assembly.inventory_id, prev_declaration_id=None,
                                             declared_exposures=(), declared_t_sel_utc=None, declared_trial_counts=None)
    chronology = ChronologyFacts(None, None, TimeProofFact(TimeProofStatus.ABSENT, None, None), None, None, None, None)
    result = classify_exposure(ClassificationInput(assembly.inventory, DeclarationSet((declaration,), True), chronology, assembly.own_context))
    return assembly, result


def test_reason_codes_are_literal_and_distinct_from_the_historical_ones():
    assert (v5.REASON_RUN_OUTPUT_UNVERIFIED, v5.REASON_RUN_EVIDENCE_UNVERIFIED, v5.REASON_RUN_ORPHAN) == (
        "RUN_OUTPUT_UNVERIFIED", "RUN_EVIDENCE_UNVERIFIED", "RUN_ORPHAN")
    assert not {v5.REASON_RUN_OUTPUT_UNVERIFIED, v5.REASON_RUN_EVIDENCE_UNVERIFIED, v5.REASON_RUN_ORPHAN} & {r.value for r in b3.IncompleteReason}


# ══ B3-v5A-2 : preuves de run (couverture, sessions, sceau) ═══════════════════════════════════════════════════════════════════════
def test_valid_run_evidence_is_recognised_read_strictly_and_stays_unresolved_with_its_raw_bytes_hash(tmp_path):
    files = evidence_files()
    result = interpret_v5(build(tmp_path, files))
    assert result.semantics_version == v5.B3_V5_SEMANTICS_VERSION and result.complete is False
    for path, data in files.items():
        tag = {"run_data_coverage.json": "validation.coverage", "run_session_0001.json": "validation.session", "run_seal.json": "validation.seal"}[path.rsplit("/", 1)[1]]
        found = finding_of(result, f"{tag}:camp/{path}")
        assert (found.source_kind, found.status, found.overlap, found.unresolved_cause, found.content_hash) == (
            SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN, UnresolvedCause.WINDOW_UNKNOWN, sha(data))
        assert f"RUN_EVIDENCE_UNVERIFIED:camp/{path}" in result.incomplete_reasons
    wf = finding_of(result, f"validation.run:camp/validations/{RUN_WF_ID}/validation_run.json")
    assert (wf.source_kind, wf.status, wf.unresolved_cause) == (SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, UnresolvedCause.WINDOW_UNKNOWN)
    assert [n.validation_type for n in result.non_oos_validations] == ["walk_forward"]


def normative(record) -> bytes:
    """Octets normatifs (ADR 0025 23.29.4) écrits ici à la main : clés triées, indent=2, LF final, UTF-8, sans NaN (les flottants ne sont PAS refusés à l'écriture)."""
    return (json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def mutated(record_of, mutate):
    record = copy.deepcopy(record_of)
    mutate(record)
    return normative(record)


def invalid_evidence_cases():
    coverage, session, seal = (m.to_record() for m in evidence_models())
    base = f"validations/{RUN_WF_ID}"
    cov_path, ses_path, seal_path = f"{base}/run_data_coverage.json", f"{base}/run_session_0001.json", f"{base}/run_seal.json"
    wrong_run = RUN_WF_ID.replace("cd", "ef", 1)
    return [
        ("coverage extra key", cov_path, mutated(coverage, lambda r: r.update(extra=1))),
        ("coverage wrong version", cov_path, mutated(coverage, lambda r: r.update(coverage_semantics_version="gate_v_run_data_coverage_v2"))),
        ("coverage run id of another run", cov_path, mutated(coverage, lambda r: r.update(validation_run_id=wrong_run))),
        ("coverage run id of a derived run in a WF directory", cov_path, mutated(coverage, lambda r: r.update(validation_run_id=RUN_MC_ID))),
        ("coverage DERIVED binding", cov_path, mutated(coverage, lambda r: r.update(binding_kind="DERIVED"))),
        ("coverage not normative bytes", cov_path, json.dumps(coverage, indent=4, sort_keys=True).encode()),
        ("coverage a float", cov_path, mutated(coverage, lambda r: r.update(source_size_bytes=1.5))),
        ("session extra key", ses_path, mutated(session, lambda r: r.update(extra=1))),
        ("session index zero", f"{base}/run_session_0000.json", mutated(session, lambda r: r.update(session_index=0))),
        ("session file number differs from the record index", f"{base}/run_session_0002.json", normative(session)),
        ("session run id of another run", ses_path, mutated(session, lambda r: r.update(validation_run_id=wrong_run))),
        ("seal extra key", seal_path, mutated(seal, lambda r: r.update(extra=1))),
        ("seal run id of another run", seal_path, mutated(seal, lambda r: r.update(validation_run_id=wrong_run))),
        ("seal of a derived type", seal_path, mutated(seal, lambda r: r.update(validation_type="monte_carlo"))),
        ("seal wrong version", seal_path, mutated(seal, lambda r: r.update(seal_semantics_version="gate_v_run_seal_v2"))),
        ("seal listing a path outside walk_forward", seal_path, mutated(seal, lambda r: r["output_artifacts"].append({"path": "../x", "sha256": "ab" * 32, "size": 1}))),
    ]


@pytest.mark.parametrize("label, path, data", invalid_evidence_cases(), ids=lambda value: value if isinstance(value, str) and len(value) < 60 and "/" not in value else None)
def test_invalid_or_incoherent_run_evidence_is_refused_as_an_unresolved_invalid_schema_source(tmp_path, label, path, data):
    result = interpret_v5(build(tmp_path, {path: data}))
    tag = {"run_data_coverage.json": "validation.coverage", "run_seal.json": "validation.seal"}.get(path.rsplit("/", 1)[1], "validation.session")
    found = finding_of(result, f"{tag}:camp/{path}")
    assert (found.source_kind, found.status, found.unresolved_cause, found.content_hash) == (
        SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, UnresolvedCause.INVALID_SCHEMA, sha(data))
    assert f"INFORMATIVE_UNRESOLVED:camp/{path}" in result.incomplete_reasons
    assert not reasons_with(result, "RUN_EVIDENCE_UNVERIFIED") and result.complete is False


@pytest.mark.parametrize("raw", [b"{not json", b"[]", b"\xef\xbb\xbf{}", b'{"a": 1, "a": 2}', b"\xff\xfe"])
def test_run_evidence_that_the_strict_reader_cannot_parse_is_a_source_anomaly_with_no_evidence_claim(tmp_path, raw):
    path = f"validations/{RUN_WF_ID}/run_seal.json"
    result = interpret_v5(build(tmp_path, {path: raw}))
    found = finding_of(result, f"validation.seal:camp/{path}")
    assert found.status is SourceStatus.UNRESOLVED and found.unresolved_cause in (UnresolvedCause.UNREADABLE, UnresolvedCause.INVALID_SCHEMA)
    assert f"SOURCE_ANOMALY:camp/{path}" in result.incomplete_reasons and not reasons_with(result, "RUN_EVIDENCE_UNVERIFIED")


@pytest.mark.parametrize("run_id", [RUN_MC_ID, RUN_PS_ID])
def test_run_evidence_in_a_derived_run_directory_is_not_recognised_so_derived_coverage_stays_blocked(tmp_path, run_id):
    path = f"validations/{run_id}/run_data_coverage.json"
    result = interpret_v5(build(tmp_path, {path: evidence_files()[f"validations/{RUN_WF_ID}/run_data_coverage.json"]}, run_record_for=run_id))
    assert f"UNKNOWN_ENTRY:camp/{path}" in result.incomplete_reasons
    found = finding_of(result, f"unknown:camp/{path}")
    assert (found.status, found.unresolved_cause) == (SourceStatus.UNRESOLVED, UnresolvedCause.UNKNOWN_SOURCE_TYPE)


def test_evidence_is_never_taken_from_a_session_file_with_a_wrong_name_or_a_wrong_directory(tmp_path):
    session = evidence_files()[f"validations/{RUN_WF_ID}/run_session_0001.json"]
    odd = {f"validations/{RUN_WF_ID}/run_session_1.json": session, f"validations/{RUN_WF_ID}/run_session_00001.json": session,
           f"validations/{RUN_WF_ID}/run_session_0001.json.bak": session, f"validations/{RUN_WF_ID}/RUN_SEAL.json": session,
           "run_seal.json": session, f"validations/run_seal.json": session}
    result = interpret_v5(build(tmp_path, odd))
    for path in odd:
        assert f"UNKNOWN_ENTRY:camp/{path}" in result.incomplete_reasons, path


# ══ B3-v5A-6 (partie 1) : une chaîne de preuves incomplète ou isolée ne prouve jamais rien ═══════════════════════════════════════════
@pytest.mark.parametrize("keep, run_record_for", [
    ((), RUN_WF_ID),                                                                     # run WF sans couverture
    (("run_data_coverage.json",), RUN_WF_ID),                                            # couverture sans session
    (("run_data_coverage.json", "run_session_0001.json"), RUN_WF_ID),                    # session sans sceau
    (("run_data_coverage.json", "run_session_0001.json", "run_seal.json"), None),        # chaîne complète sans ValidationRun
    (("run_seal.json",), None),                                                          # sceau seul sans ValidationRun
    (("run_data_coverage.json", "run_session_0001.json", "run_seal.json"), RUN_WF_ID),   # chaîne complète (non vérifiée : L3)
], ids=["no-coverage", "coverage-without-session", "session-without-seal", "chain-without-run", "seal-alone", "complete-chain-unverified"])
def test_no_combination_of_run_evidence_files_can_make_the_inventory_complete_or_fresh(tmp_path, keep, run_record_for):
    files = {path: data for path, data in evidence_files().items() if path.rsplit("/", 1)[1] in keep}
    interpretation = interpret_v5(build(tmp_path, files, run_record_for=run_record_for))
    assert interpretation.complete is False or not keep                                    # sans fichier de preuve : comportement de v4 (voir le test d'identité)
    assert any(f.status is SourceStatus.UNRESOLVED for f in interpretation.findings) or reasons_with(interpretation, "MISSING_REQUIRED")
    _, result = classification_of(interpretation)
    assert result.classification is ExposureClass.UNDETERMINED
    assert result.classification is not ExposureClass.FRESH_UNEXPOSED_DECLARED
    if run_record_for is None and keep:
        assert reasons_with(interpretation, "MISSING_REQUIRED")                          # l'ancre manque : jamais une absence « établie »


def test_a_tree_without_any_v5_artifact_is_interpreted_exactly_like_v4_except_for_the_version(tmp_path):
    directory = build(tmp_path, {})
    historical = b3.interpret_audit_roots((b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory))),), LIMITS,
                                          holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = interpret_v5(directory)
    assert (current.findings, current.plans, current.complete, current.incomplete_reasons, current.non_oos_validations, current.exposure_evidence) == (
        historical.findings, historical.plans, historical.complete, historical.incomplete_reasons, historical.non_oos_validations, historical.exposure_evidence)
    assert (historical.semantics_version, current.semantics_version) == (V4, v5.B3_V5_SEMANTICS_VERSION)
    assert current.scans[0].scan.hash_limits == HL and historical.scans[0].scan.hash_limits is None


# ══ B3-v5A-3 : sorties Walk-Forward hachées ════════════════════════════════════════════════════════════════════════════════════════
def expected_output_tag(path: str) -> str:
    name = path.rsplit("/", 1)[1]
    if path.startswith("walk_forward/.gate_v_checkpoints_v1/"):
        return "wf.checkpoint.manifest" if name == "manifest.json" else "wf.checkpoint.fold"
    if "/folds/" in path:
        return "wf.output.fold_csv" if name.endswith(".csv") else "wf.output.fold_json"
    return {"manifest.json": "wf.output.manifest", "state.json": "wf.output.state", "aggregate.json": "wf.output.aggregate"}[name]


def test_a_complete_walk_forward_output_tree_is_hashed_byte_exactly_never_interpreted_and_every_output_stays_unresolved(tmp_path):
    outputs = wf_outputs()
    result = interpret_v5(build(tmp_path, outputs))
    scanned = result.scans[0].scan
    assert (scanned.hash_limits, scanned.hashed_files, scanned.hashed_bytes_read) == (HL, len(outputs), sum(len(data) for data in outputs.values()))
    observed = {o.relative_path: o for o in scanned.observations}
    for path, data in outputs.items():
        o = observed[path]
        assert (o.entry_class, o.content_hash, o.value_parsed, o.content_bytes, o.size) == (scan.EntryClass.HASHED_FILE, sha(data), False, None, len(data))
        found = finding_of(result, f"{expected_output_tag(path)}:camp/{path}")
        assert (found.source_kind, found.status, found.overlap, found.unresolved_cause, found.content_hash) == (
            SourceKind.UNKNOWN_SOURCE, SourceStatus.UNRESOLVED, OverlapVerdict.UNKNOWN, UnresolvedCause.WINDOW_UNKNOWN, sha(data))
        assert f"RUN_OUTPUT_UNVERIFIED:camp/{path}" in result.incomplete_reasons
    assert len(reasons_with(result, "RUN_OUTPUT_UNVERIFIED")) == len(outputs) + N_WF_DIRECTORIES and result.complete is False          # fichiers + répertoires
    for directory in ("walk_forward", "walk_forward/folds", "walk_forward/folds/fold_000", "walk_forward/.gate_v_checkpoints_v1", "walk_forward/.gate_v_checkpoints_v1/folds"):
        assert f"RUN_OUTPUT_UNVERIFIED:camp/{directory}" in result.incomplete_reasons
    assert not reasons_with(result, "UNKNOWN_ENTRY") and not reasons_with(result, "SOURCE_ANOMALY")


UNKNOWN_UNDER_WALK_FORWARD = [
    ("walk_forward/notes.txt", "walk_forward/notes.txt"),
    ("walk_forward/folds/notes.txt", "walk_forward/folds/notes.txt"),
    ("walk_forward/folds/fold_000/notes.txt", "walk_forward/folds/fold_000/notes.txt"),
    ("walk_forward/folds/fold_000/train_progress.csv", "walk_forward/folds/fold_000/train_progress.csv"),     # reprise héritée : trace d'interruption
    ("walk_forward/folds/fold_00/definition.json", "walk_forward/folds/fold_00"),
    ("walk_forward/folds/fold_0000/definition.json", "walk_forward/folds/fold_0000"),
    ("walk_forward/folds/fold_000_/definition.json", "walk_forward/folds/fold_000_"),                        # (Windows ignore la casse : pas de `Fold_000`)
    ("walk_forward/folds/definition.json", "walk_forward/folds/definition.json"),                              # mauvais dossier
    ("walk_forward/definition.json", "walk_forward/definition.json"),
    ("walk_forward/fold_000/definition.json", "walk_forward/fold_000"),
    ("walk_forward/.gate_v_checkpoints_v1/state.json", "walk_forward/.gate_v_checkpoints_v1/state.json"),
    ("walk_forward/.gate_v_checkpoints_v1/folds/fold_000/x.json", "walk_forward/.gate_v_checkpoints_v1/folds/fold_000"),
    ("walk_forward/.gate_v_checkpoints_v1/folds/fold_000.json.bak", "walk_forward/.gate_v_checkpoints_v1/folds/fold_000.json.bak"),
    ("walk_forward/.gate_v_checkpoints_v2/manifest.json", "walk_forward/.gate_v_checkpoints_v2"),
    ("walk_forward/folds/fold_000/sub/definition.json", "walk_forward/folds/fold_000/sub"),
    ("walk_forward/manifest.json.bak", "walk_forward/manifest.json.bak"),
]


@pytest.mark.parametrize("created, unknown", UNKNOWN_UNDER_WALK_FORWARD, ids=[f"unknown-{i:02d}" for i in range(len(UNKNOWN_UNDER_WALK_FORWARD))])
def test_unknown_misplaced_or_substituted_files_under_walk_forward_stay_unknown_blocking_and_unhashed(tmp_path, created, unknown):
    outputs = wf_outputs()
    interpretation = interpret_v5(build(tmp_path, {**outputs, created: b"surprise"}))
    assert f"UNKNOWN_ENTRY:camp/{unknown}" in interpretation.incomplete_reasons
    found = finding_of(interpretation, f"unknown:camp/{unknown}")
    assert (found.status, found.unresolved_cause, found.content_hash) == (SourceStatus.UNRESOLVED, UnresolvedCause.UNKNOWN_SOURCE_TYPE, None)
    assert interpretation.scans[0].scan.hashed_files == len(outputs)                           # l'intrus n'est jamais haché
    assert classification_of(interpretation)[1].classification is ExposureClass.UNDETERMINED


def test_a_directory_in_place_of_an_output_file_and_a_file_in_place_of_a_directory_are_kind_mismatch_anomalies(tmp_path):
    outputs = wf_outputs()
    directory = build(tmp_path, {path: data for path, data in outputs.items() if path != "walk_forward/aggregate.json"})
    (directory / "walk_forward" / "aggregate.json").mkdir()
    result = interpret_v5(directory)
    assert "SOURCE_ANOMALY:camp/walk_forward/aggregate.json" in result.incomplete_reasons
    found = finding_of(result, "wf.output.aggregate:camp/walk_forward/aggregate.json")
    assert (found.status, found.unresolved_cause, found.content_hash) == (SourceStatus.UNRESOLVED, UnresolvedCause.INVALID_SCHEMA, None)
    as_file = build(tmp_path / "second", {"walk_forward": b"not a directory"})
    second = interpret_v5(as_file)
    assert "SOURCE_ANOMALY:camp/walk_forward" in second.incomplete_reasons and second.scans[0].scan.hashed_files == 0


def test_changing_one_byte_of_one_output_changes_its_finding_hash_and_the_inventory_identity_and_the_same_tree_is_deterministic(tmp_path):
    outputs = wf_outputs()
    path = "walk_forward/folds/fold_001/oos_trades.csv"
    first, again = interpret_v5(build(tmp_path / "a", outputs)), interpret_v5(build(tmp_path / "b", outputs))
    changed = interpret_v5(build(tmp_path / "c", {**outputs, path: outputs[path] + b"x"}))
    tag = "wf.output.fold_csv"
    assert finding_of(changed, f"{tag}:camp/{path}").content_hash == sha(outputs[path] + b"x") != finding_of(first, f"{tag}:camp/{path}").content_hash
    ids = [classification_of(item)[0].inventory_id for item in (first, again, changed)]
    assert ids[0] == ids[1] != ids[2]


def test_a_missing_expected_output_is_never_an_absence_of_exposure_and_is_never_invented(tmp_path):
    outputs = wf_outputs()
    del outputs["walk_forward/aggregate.json"]
    result = interpret_v5(build(tmp_path, outputs))
    assert not [f for f in result.findings if f.source_id.startswith("wf.output.aggregate:")]
    assert result.complete is False and classification_of(result)[1].classification is ExposureClass.UNDETERMINED
    assert result.scans[0].scan.hashed_files == len(outputs)


def test_hash_limits_are_mandatory_typed_and_never_defaulted(tmp_path):
    directory = build(tmp_path, wf_outputs())
    root = b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("camp", str(directory)))
    with pytest.raises(TypeError):
        v5.interpret_audit_roots_v5((root,), LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])           # aucun plafond par défaut
    for bad in (None, LIMITS, {"max_hashed_files": 1}, 1024):
        with pytest.raises(TypeError):
            v5.interpret_audit_roots_v5((root,), LIMITS, hash_limits=bad, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])


def test_hashed_budgets_are_enforced_a_total_or_count_overrun_refuses_and_an_oversized_file_is_an_anomaly_without_hash(tmp_path):
    outputs = wf_outputs()
    directory = build(tmp_path, outputs)
    for limits in (HashLimits(max_hashed_file_bytes=100, max_total_hashed_bytes=100, max_hashed_files=200),
                   HashLimits(max_hashed_file_bytes=65_536, max_total_hashed_bytes=2_000_000, max_hashed_files=3)):
        with pytest.raises(ExposureScanRefusal) as info:
            interpret_v5(directory, hl=limits)
        assert info.value.failure is StructuralFailure.LIMIT_EXCEEDED
    big = "walk_forward/folds/fold_000/oos_equity.csv"
    result = interpret_v5(build(tmp_path / "big", {**outputs, big: b"x" * 200}), hl=HashLimits(max_hashed_file_bytes=100, max_total_hashed_bytes=2_000_000, max_hashed_files=200))
    found = finding_of(result, f"wf.output.fold_csv:camp/{big}")
    assert (found.status, found.unresolved_cause, found.content_hash) == (SourceStatus.UNRESOLVED, UnresolvedCause.UNREADABLE, None)
    assert f"SOURCE_ANOMALY:camp/{big}" in result.incomplete_reasons and not [r for r in result.incomplete_reasons if r.endswith(big) and r.startswith("RUN_OUTPUT")]


def rewrite_in_place(path, data: bytes) -> None:
    """Remplace le contenu SANS changer taille, inode ni mtime : invisible aux seules métadonnées, détecté par le hash de la seconde passe."""
    before = os.stat(path)
    with open(path, "r+b") as handle:
        handle.write(data)
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))


def test_a_same_size_edit_between_the_two_passes_refuses_the_scan_as_unstable(tmp_path):
    outputs = wf_outputs()
    directory = build(tmp_path, outputs)
    target = directory / "walk_forward" / "state.json"
    size = len(outputs["walk_forward/state.json"])
    hooks = ScanHooks(after_first_pass=lambda attempt: rewrite_in_place(target, b"Z" * size))
    with pytest.raises(ExposureScanRefusal) as info:
        interpret_v5(directory, hooks=hooks)
    assert info.value.failure is StructuralFailure.UNSTABLE_LISTING


def test_a_file_growing_between_listing_and_opening_refuses_the_scan_as_unstable(tmp_path):
    directory = build(tmp_path, wf_outputs())
    target = directory / "walk_forward" / "aggregate.json"

    def grow(_label, path):
        if path == "walk_forward/aggregate.json":
            target.write_bytes(b"g" * 4096)
    with pytest.raises(ExposureScanRefusal) as info:
        interpret_v5(directory, hooks=ScanHooks(before_open=grow))
    assert info.value.failure is StructuralFailure.UNSTABLE_LISTING


def test_a_symbolic_link_in_the_output_tree_refuses_the_scan(tmp_path):
    directory = build(tmp_path, wf_outputs())
    link = directory / "walk_forward" / "link.json"
    try:
        os.symlink(directory / "walk_forward" / "state.json", link)
    except (OSError, NotImplementedError):
        pytest.skip("liens symboliques non disponibles sur ce système")
    with pytest.raises(ExposureScanRefusal) as info:
        interpret_v5(directory)
    assert info.value.failure is StructuralFailure.LINK_OR_REPARSE_POINT


def test_a_foreign_campaign_with_an_anomaly_keeps_the_whole_inventory_blocking(tmp_path):
    own = build(tmp_path / "own", wf_outputs())
    foreign = build(tmp_path / "foreign", {"walk_forward/mystery.bin": b"x"}, name="gate_v_v2_" + "ee" * 32, run_record_for=None)
    roots = (b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("own", str(own))), b3.LayoutRoot(b3.RootLayout.CAMPAIGN_DIR, AuditRoot("foreign", str(foreign))))
    result = v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    assert "UNKNOWN_ENTRY:foreign/walk_forward/mystery.bin" in result.incomplete_reasons and result.complete is False
    assert classification_of(result)[1].classification is ExposureClass.UNDETERMINED


# ══ B3-v5A-4 : orphelins de publication ═══════════════════════════════════════════════════════════════════════════════════════════
A32 = "a" * 32
ORPHAN_TARGETS = ["walk_forward/manifest.json", "walk_forward/state.json", "walk_forward/aggregate.json", "walk_forward/folds/fold_000/definition.json",
                  "walk_forward/folds/fold_000/selection.json", "walk_forward/folds/fold_000/test_result.json",
                  "walk_forward/.gate_v_checkpoints_v1/manifest.json", "walk_forward/.gate_v_checkpoints_v1/folds/fold_000.json"]


@pytest.mark.parametrize("target", ORPHAN_TARGETS, ids=[f"target-{i}" for i in range(len(ORPHAN_TARGETS))])
@pytest.mark.parametrize("target_present", [True, False], ids=["target-present", "target-absent"])
def test_the_interrupted_write_of_a_known_target_is_a_recognised_blocking_orphan_never_the_output_itself(tmp_path, target, target_present):
    outputs = wf_outputs()
    if not target_present:
        del outputs[target]
    orphan = f"{target}.{A32}.tmp"
    result = interpret_v5(build(tmp_path, {**outputs, orphan: b"half-written"}))
    observed = {o.relative_path: o for o in result.scans[0].scan.observations}
    assert (observed[orphan].entry_class, observed[orphan].content_hash, observed[orphan].value_parsed) == (ORPHAN, None, False)
    assert (target in observed) is target_present and result.scans[0].scan.hashed_files == len(outputs)
    assert f"RUN_ORPHAN:camp/{orphan}" in result.incomplete_reasons and not reasons_with(result, "UNKNOWN_ENTRY")
    found = finding_of(result, f"wf.output.orphan:camp/{orphan}")
    assert (found.status, found.unresolved_cause, found.content_hash) == (SourceStatus.UNRESOLVED, UnresolvedCause.UNKNOWN_SOURCE_TYPE, None)
    assert result.complete is False


@pytest.mark.parametrize("run_id", [RUN_WF_ID, RUN_MC_ID, RUN_PS_ID])
def test_the_orphan_of_a_validation_run_is_recognised_but_never_satisfies_the_anchor(tmp_path, run_id):
    orphan = f"validations/{run_id}/validation_run.json.{A32}.tmp"
    result = interpret_v5(build(tmp_path, {orphan: b"{}"}, run_record_for=None))
    assert f"RUN_ORPHAN:camp/{orphan}" in result.incomplete_reasons
    assert f"MISSING_REQUIRED:camp/validations/{run_id}/validation_run.json" in result.incomplete_reasons         # l'orphelin ne remplace jamais le run attendu
    assert any(f.status is SourceStatus.UNRESOLVED and f.source_id.startswith("validation.run:") for f in result.findings)
    assert classification_of(result)[1].classification is ExposureClass.UNDETERMINED


FORGED_TEMPORARIES = [
    f"walk_forward/aggregate.json.{'A' * 32}.tmp", f"walk_forward/aggregate.json.{'a' * 31}.tmp", f"walk_forward/aggregate.json.{'a' * 33}.tmp",
    "walk_forward/aggregate.json.tmp", f"walk_forward/aggregate.json.{A32}.tmp.bak", f"walk_forward/other.json.{A32}.tmp",
    f"walk_forward/folds/aggregate.json.{A32}.tmp", f"walk_forward/folds/fold_000/train_candidates.csv.{A32}.tmp",
    f"walk_forward/folds/fold_000/oos_trades.csv.{A32}.tmp", f"walk_forward/.exposure.tmp.{A32}", f"walk_forward/aggregate.json.exposure.tmp.{A32}",
    f"walk_forward/manifest.json.{A32}.tmp.{A32}.tmp", f"validations/{RUN_WF_ID}/run_seal.json.{A32}.tmp",
    f"validations/{RUN_WF_ID}/run_data_coverage.json.{A32}.tmp", f"validations/{RUN_WF_ID}/run_session_0001.json.{A32}.tmp",
    f"plan.json.{A32}.tmp", f"manifest.json.{A32}.tmp", f"walk_forward/.gate_v_checkpoints_v1/folds/fold_000.json.{A32}.tmp.x",
    f"walk_forward/.gate_v_checkpoints_v1/state.json.{A32}.tmp",
]


@pytest.mark.parametrize("forged", FORGED_TEMPORARIES, ids=[f"forged-{i:02d}" for i in range(len(FORGED_TEMPORARIES))])
def test_a_forged_unsupported_or_misplaced_temporary_is_an_unknown_blocking_entry_and_neutralises_nothing(tmp_path, forged):
    outputs = wf_outputs()
    result = interpret_v5(build(tmp_path, {**outputs, **evidence_files(), forged: b"x"}))
    assert f"UNKNOWN_ENTRY:camp/{forged}" in result.incomplete_reasons and not reasons_with(result, "RUN_ORPHAN")
    assert len(reasons_with(result, "RUN_OUTPUT_UNVERIFIED")) == len(outputs) + N_WF_DIRECTORIES and len(reasons_with(result, "RUN_EVIDENCE_UNVERIFIED")) == 3
    assert result.scans[0].scan.hashed_files == len(outputs)


def test_the_historical_exposure_orphan_keeps_its_v4_behaviour_and_is_not_a_run_orphan(tmp_path):
    files = {f"exposure/.exposure.tmp.{A32}": b"half"}
    directory = build(tmp_path, files, run_record_for=None)
    historical = b3.interpret_audit_roots((b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory))),), LIMITS,
                                          holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = interpret_v5(directory)
    assert current.incomplete_reasons == historical.incomplete_reasons and not reasons_with(current, "RUN_ORPHAN")


def test_a_tree_with_every_recognised_artifact_is_scanned_without_any_ambiguity(tmp_path):
    files = {**wf_outputs(), **evidence_files(), f"exposure/.exposure.tmp.{A32}": b"x", f"exposure/inventory_{'1' * 64}.json": b"{}",
             f"validations/{RUN_MC_ID}/validation_run.json": json.dumps(run_record(RUN_MC_ID, "monte_carlo")).encode(),
             f"validations/{RUN_PS_ID}/validation_run.json": json.dumps(run_record(RUN_PS_ID, "parameter_stability")).encode(),
             f"validations/{RUN_WF_ID}/validation_run.json.{A32}.tmp": b"x", "manifest.json": b"{}"}
    files.update({f"{target}.{A32}.tmp": b"half" for target in ORPHAN_TARGETS})
    result = interpret_v5(build(tmp_path, files))                                         # aucune AMBIGUOUS_SOURCE_TABLE : chaque chemin a au plus une règle
    kinds = {o.entry_class for o in result.scans[0].scan.observations}
    assert {scan.EntryClass.HASHED_FILE, scan.EntryClass.TEMP_ORPHAN_FILE, scan.EntryClass.EXPOSING_JSON, scan.EntryClass.STRUCTURAL_DIRECTORY} <= kinds
    assert result.complete is False


# ══ B3-v5A-6 : non-régression scientifique (v5 n'est jamais moins bloquant que v4) ═════════════════════════════════════════════════════
EMPTY_RUN_DIRECTORIES = ["walk_forward", "walk_forward/folds", "walk_forward/folds/fold_000", "walk_forward/.gate_v_checkpoints_v1",
                         "walk_forward/.gate_v_checkpoints_v1/folds"]
N_WF_DIRECTORIES = 2 + len(FOLDS) + 2          # walk_forward, folds, un dossier par fold, checkpoints, checkpoints/folds


@pytest.mark.parametrize("directory_path", EMPTY_RUN_DIRECTORIES, ids=[f"empty-{i}" for i in range(len(EMPTY_RUN_DIRECTORIES))])
def test_a_skeleton_of_walk_forward_directories_without_any_file_still_blocks_exactly_like_v4(tmp_path, directory_path):
    """Défaut démontré par la revue indépendante : un dossier fold créé APRÈS le calcul du fold, puis vidé, ne doit jamais redevenir « rien à signaler »."""
    directory = build(tmp_path, {}, run_record_for=None)
    (directory / directory_path).mkdir(parents=True)
    historical = b3.interpret_audit_roots((b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory))),), LIMITS,
                                          holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = interpret_v5(directory)
    assert historical.complete is False and current.complete is False
    assert f"RUN_OUTPUT_UNVERIFIED:camp/{directory_path}" in current.incomplete_reasons
    assert any(f.status is SourceStatus.UNRESOLVED and f.source_id.endswith(f":camp/{directory_path}") for f in current.findings)
    assert classification_of(current)[1].classification is ExposureClass.UNDETERMINED
    assert classification_of(historical)[1].classification is ExposureClass.UNDETERMINED

def test_on_random_trees_v5_is_never_less_blocking_than_v4_and_never_creates_a_fresh_classification(tmp_path):
    import random
    generator = random.Random(20261025)
    pool = {**wf_outputs(), **evidence_files(), f"walk_forward/aggregate.json.{A32}.tmp": b"half", f"validations/{RUN_WF_ID}/validation_run.json.{A32}.tmp": b"half",
            "walk_forward/notes.txt": b"x", f"validations/{RUN_MC_ID}/run_data_coverage.json": b"{}", "manifest.json": b"{}", f"exposure/.exposure.tmp.{A32}": b"x"}
    paths = sorted(pool)
    v5_paths = {p for p in paths if p.startswith("walk_forward/") and not p.endswith("notes.txt") or p.startswith(f"validations/{RUN_WF_ID}/run_")
                or p == f"validations/{RUN_WF_ID}/validation_run.json.{A32}.tmp"} | set(EMPTY_RUN_DIRECTORIES)
    differing = freshable_rounds = 0
    for round_number in range(40):
        chosen = {p: pool[p] for p in paths if generator.random() < generator.choice((0.1, 0.5, 0.9))}
        with_run = generator.random() < 0.5
        empty_dirs = [d for d in EMPTY_RUN_DIRECTORIES if generator.random() < 0.3]        # squelettes de répertoires sans fichier (défaut F1 de la revue)
        if round_number < 2:                                      # tours déterministes : une campagne propre (ancre seule), qui doit rester « fraîchable » pour v4 ET v5
            chosen, with_run, empty_dirs = {}, False, []
        directory = build(tmp_path / f"r{round_number}", chosen, run_record_for=RUN_WF_ID if with_run else None)
        for empty in empty_dirs:
            (directory / empty).mkdir(parents=True, exist_ok=True)
        chosen = {**chosen, **{d: b"" for d in empty_dirs}}                                  # (pour le test « contient un artefact v5 » ci-dessous)
        historical = b3.interpret_audit_roots((b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory))),), LIMITS,
                                              holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
        current = interpret_v5(directory)
        class_v4, class_v5 = classification_of(historical)[1].classification, classification_of(current)[1].classification
        assert (not historical.complete) <= (not current.complete), sorted(chosen)                         # v4 incomplet ⇒ v5 incomplet, SANS exemption
        unresolved = lambda interpretation: any(f.status is SourceStatus.UNRESOLVED for f in interpretation.findings)       # noqa: E731
        assert unresolved(historical) <= unresolved(current), sorted(chosen)                                # v4 a un finding non résolu ⇒ v5 aussi
        if class_v4 is not ExposureClass.FRESH_UNEXPOSED_DECLARED:
            assert class_v5 is not ExposureClass.FRESH_UNEXPOSED_DECLARED, sorted(chosen)

        def freshable(interpretation):          # précondition de B3 pour FRESH : complète ET que des sources résolues sans recouvrement
            return interpretation.complete and all(f.status is SourceStatus.RESOLVED and f.overlap is OverlapVerdict.NO_OVERLAP for f in interpretation.findings)
        if freshable(current):
            assert freshable(historical) and not set(chosen) & v5_paths, sorted(chosen)                 # v5 « fraîchable » ⇒ v4 l'est, sans artefact v5
        freshable_rounds += freshable(current)
        differing += (historical.findings != current.findings)
    assert differing > 0 and freshable_rounds > 0                              # non vacueux : v5 produit des findings différents, et des arbres « fraîchables » existent


def test_v5_equals_v4_on_a_rich_historical_tree_for_every_historical_source(tmp_path):
    """Garde différentielle de la boucle d'orchestration recopiée (constat F6 de la revue) : jobs exposé et disjoint, expérience, validation OOS, ancre de campagne."""
    from tests.gate_v_exposure_support import make_job
    results = tmp_path / "results"
    make_job(results, "job_1", "2026-02-01T00:00:00+00:00", "2026-02-10T00:00:00+00:00")
    make_job(results, "job_2", "2025-06-01T00:00:00+00:00", "2025-06-10T00:00:00+00:00")
    write_json(results / "experiments" / "exp_1.json", {"created_at": "2025-01-01T00:00:00+00:00", "experiment_id": "exp_1", "hypothesis": "h"})
    oos = {**run_record("val_oos_1", "oos"), "evidence": {"period_start": "2026-02-01T00:00:00+00:00", "period_end": "2026-02-05T00:00:00+00:00"}}
    write_json(results / "validations" / "val_oos_1" / "validation_run.json", oos)
    campaign = build(tmp_path / "campaign", {})
    roots = (b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(results))), b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(campaign))))
    historical = b3.interpret_audit_roots(roots, LIMITS, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    current = v5.interpret_audit_roots_v5(roots, LIMITS, hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    fields = ("findings", "plans", "complete", "incomplete_reasons", "non_oos_validations", "exposure_evidence")
    assert [getattr(historical, name) for name in fields] == [getattr(current, name) for name in fields]
    assert any(f.overlap is OverlapVerdict.OVERLAPS for f in current.findings) and len(current.findings) >= 4          # le test n'est pas vacueux


@pytest.mark.parametrize("record_type", ["RESERVATION", "ADMISSION"])
def test_the_registry_preconditions_refuse_every_inventory_built_with_recognised_run_artifacts(tmp_path, record_type):
    from gate_v_inventory_preconditions import InventoryPreconditionRefusal as Refusal, RegistryRecordType, inventory_precondition_refusals
    interpretation = interpret_v5(build(tmp_path, {**wf_outputs(), **evidence_files()}))
    assembly, _ = classification_of(interpretation)
    stage = OwnRecordStage.NO_OWN_RECORDS if record_type == "RESERVATION" else OwnRecordStage.RESERVED
    report = inventory_precondition_refusals(RegistryRecordType[record_type], assembly.inventory, OwnCampaignContext("campaign_current", stage))
    assert report.inventory_part_satisfied is False
    assert Refusal.INVENTORY_INCOMPLETE in report.refusals and (Refusal.RELEVANT_SET_NOT_EMPTY in report.refusals or Refusal.UNRESOLVED_OR_EXPOSING_SOURCE in report.refusals)


# ── Gardes d'orchestration (v5 réécrit la boucle de B3 : chacune est retestée) ──────────────────────────────────────────────────────
def test_orchestration_guards_match_those_of_v3_v4_roots_types_overlap_labels_window_and_hooks(tmp_path):
    directory = build(tmp_path, {})
    root = b3.LayoutRoot(CAMPAIGN, AuditRoot("camp", str(directory)))
    nested = b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("res", str(directory / "validations")))
    clone = b3.LayoutRoot(b3.RootLayout.RESULTS, AuditRoot("camp", str(tmp_path / "other")))
    call = dict(hash_limits=HL, holdout_window_start_utc=W[0], holdout_window_end_utc=W[1])
    for bad in ([root], (root, "x"), (AuditRoot("camp", str(directory)),)):
        with pytest.raises(TypeError):
            v5.interpret_audit_roots_v5(bad, LIMITS, **call)
    with pytest.raises(ExposureScanRefusal) as info:
        v5.interpret_audit_roots_v5((root, nested), LIMITS, **call)                              # racines imbriquées entre dispositions
    assert info.value.failure is StructuralFailure.ROOT_OVERLAP
    with pytest.raises(ExposureScanRefusal) as info:
        v5.interpret_audit_roots_v5((root, clone), LIMITS, **call)                               # même label sur deux dispositions
    assert info.value.failure is StructuralFailure.DUPLICATE_ROOT_LABEL
    with pytest.raises(ValueError):
        v5.interpret_audit_roots_v5((root,), LIMITS, **{**call, "holdout_window_start_utc": "2026-04-01T00:00:00+00:00", "holdout_window_end_utc": W[0]})
    plain, hooked = interpret_v5(directory), interpret_v5(directory, hooks=ScanHooks(after_first_pass=lambda attempt: None))
    assert plain.hooks_used is False and hooked.hooks_used is True


def test_a_campaign_root_without_its_anchor_or_without_any_source_is_never_complete(tmp_path):
    no_anchor = build(tmp_path / "a", {}, run_record_for=None)
    (no_anchor / "plan.json").unlink()
    (no_anchor / "exposure").mkdir()                                                              # racine non vide (sinon ROOT_EMPTY) mais sans aucune source
    result = interpret_v5(no_anchor)
    assert "MISSING_REQUIRED:camp/plan.json" in result.incomplete_reasons and "ROOT_WITHOUT_SOURCE:camp" in result.incomplete_reasons and result.complete is False
    wrong_plan = build(tmp_path / "b", {}, name=CID)
    write_json(wrong_plan / "plan.json", {"campaign_id": "gate_v_v2_" + "00" * 32})                # `campaign_id` ≠ nom du dossier
    assert "INFORMATIVE_UNRESOLVED:camp/plan.json" in interpret_v5(wrong_plan).incomplete_reasons


def test_valid_run_evidence_counts_as_a_read_source_but_never_completes_the_root(tmp_path):
    only_evidence = build(tmp_path, evidence_files(), run_record_for=None)             # ni plan.json, ni validation_run.json : la preuve est la SEULE source lue
    (only_evidence / "plan.json").unlink()
    result = interpret_v5(only_evidence)
    assert "ROOT_WITHOUT_SOURCE:camp" not in result.incomplete_reasons                           # la preuve lue sans anomalie est une source lue
    assert "MISSING_REQUIRED:camp/plan.json" in result.incomplete_reasons and result.complete is False


def test_two_rules_recognising_the_same_file_are_refused_by_the_scanner_so_no_table_can_hide_a_source(tmp_path):
    ambiguous = (*v5.source_rules_v5(CAMPAIGN), scan.SourceRule(("walk_forward", scan.SegmentPattern(r"[a-z]+\.json")), scan.EntryClass.INERT_FILE, tag="shadow"))
    directory = build(tmp_path, wf_outputs())
    with pytest.raises(ExposureScanRefusal) as info:
        scan.scan_audit_roots((AuditRoot("camp", str(directory)),), ambiguous, LIMITS, hash_limits=HL)
    assert info.value.failure is StructuralFailure.AMBIGUOUS_SOURCE_TABLE
