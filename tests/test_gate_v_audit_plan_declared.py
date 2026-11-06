"""N2-b2a — diagnostic des déclarations des plans V2 (module pur `gate_v_audit_plan_declared`). Aucun accès disque, aucune donnée de marché, aucun FINAL_HOLDOUT.
Les attendus sont des littéraux (vecteurs de la note, section 5.4) ou des comptes écrits à la main ; le recalcul brut des identités n'importe pas le module testé."""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import gate_v_audit_plan_declared as pd
import gate_v_plan_declared_support as sup
from gate_v_exposure_interpreters import RootLayout
from gate_v_exposure_scan import EntryKind

MAX_JSON = sup.MAX_JSON
SOURCE = Path(pd.__file__).read_text(encoding="utf-8")


def diag(records, **kwargs):
    interp, derived, other = sup.world(records, **{k: v for k, v in kwargs.items() if k in ("counting", "extra_other")})
    return pd.diagnose(interp, derived=derived, other_campaign_count=kwargs.get("other", other), max_json_bytes=kwargs.get("max_json", MAX_JSON))


def rec(index, **changes):
    return sup.campaign_record(index, **changes)


def breakdown(result):
    return dict(result.unavailable_breakdown)


# ── Identités : littéraux de la note (5.4) + recalcul brut indépendant ───────────────────────────────────────────────────────────────────────────

RUN_VECTORS = [("run_alpha", "1" * 64, "declared_run_reference_v1_9176d54fb6c766a02f4159ea22e74336fbc7ef2b95b676bb623a3837d7b04a60"),
               ("run_alpha", "2" * 64, "declared_run_reference_v1_9eb433dfe42646713184b66e93714eb0220b0379a11f9022988bcb6305652555")]
CONFIG_VECTORS = [("sma_cross", {"fast": 10, "slow": 30}, "declared_search_configuration_v1_da64c7a0ff71a78cb74a433c32c2f63f5d375167b468b36bc7c431210e51938f"),
                  ("sma_cross", {"slow": 30, "fast": 10}, "declared_search_configuration_v1_da64c7a0ff71a78cb74a433c32c2f63f5d375167b468b36bc7c431210e51938f"),
                  ("sma_cross", {"fast": 10.0, "slow": 30}, "declared_search_configuration_v1_efb577727387adc4a6568117e02982002de72177022be07c327b66e6f73b8ad0"),
                  ("sma_cross", {"fast": True, "slow": 30}, "declared_search_configuration_v1_76fa52cb0d4851bf03812cbead606c85bdc44ed6365b4a7ca74d0639c44e449d"),
                  ("stratégie_é", {"fast": 10, "slow": 30}, "declared_search_configuration_v1_164e07976a396fed8f574a08e48cf47920c69bd0e5e6842176c74f5b16bda44b")]


def raw_sha(preimage: dict) -> str:
    return hashlib.sha256(json.dumps(preimage, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("run_id,content,expected", RUN_VECTORS)
def test_id1_run_reference_identity_matches_the_pinned_literal_and_a_raw_recomputation(run_id, content, expected):
    assert pd._run_reference_identity(run_id, content) == expected
    raw = {"declared_kind": "research_run_reference", "identity_version": "declared_run_reference_v1", "research_run_content_hash": content, "research_run_id": run_id}
    assert expected == "declared_run_reference_v1_" + raw_sha(raw)


@pytest.mark.parametrize("name,params,expected", CONFIG_VECTORS)
def test_id2_configuration_identity_matches_the_pinned_literal_and_a_raw_recomputation(name, params, expected):
    assert pd._configuration_identity(name, params, "grid", sup.SPACE) == expected
    raw = {"base_params": params, "declared_kind": "search_configuration", "identity_version": "declared_search_configuration_v1", "search_mode": "grid",
           "search_space_hash": sup.SPACE, "strategy_name": name}
    assert expected == "declared_search_configuration_v1_" + raw_sha(raw)


def test_id3_the_first_configuration_preimage_is_the_documented_literal_string():
    literal = ('{"base_params":{"fast":10,"slow":30},"declared_kind":"search_configuration","identity_version":"declared_search_configuration_v1","search_mode":"grid",'
               '"search_space_hash":"0a1b2c3d4e5f","strategy_name":"sma_cross"}')
    assert "declared_search_configuration_v1_" + hashlib.sha256(literal.encode("utf-8")).hexdigest() == CONFIG_VECTORS[0][2]


def test_id4_domains_are_separated_and_identities_distinguish_numeric_and_boolean_forms():
    identities = {v[2] for v in CONFIG_VECTORS[:1] + CONFIG_VECTORS[2:]} | {v[2] for v in RUN_VECTORS}
    assert len(identities) == 6                                                                       # 10 / 10.0 / true / é / deux runs : tous distincts
    assert not {i.split("_v1_")[0] for i in identities} - {"declared_run_reference", "declared_search_configuration"}


def test_id5_identity_prefixes_are_versioned_constants():
    assert pd.PLAN_DECLARED_SEMANTICS_VERSION == "gate_v_plan_declared_v1" and pd.MAX_CONFLICT_SAMPLE == 20
    assert pd.UNAVAILABLE_CODES == ("NO_ATTRIBUTED_ROOT", "PLAN_CAMPAIGN_ID_MISMATCH", "PLAN_FIELD_INVALID", "PLAN_RECORD_NOT_READ", "PREIMAGE_TOO_LARGE")


# ── Réemploi, collisions, agrégation (scénarios à k >= 2) ─────────────────────────────────────────────────────────────────────────────────────

def test_re1_the_same_run_in_two_campaigns_is_one_reference_counted_as_reused():
    result = diag([rec(0), rec(1, strategy_name="other")])
    assert (result.declared_run_reference_count, result.declared_run_id_count, result.multi_campaign_run_reference_count) == (1, 1, 1)
    assert (result.declared_search_config_count, result.multi_campaign_search_config_count, result.declared_strategy_name_count) == (2, 0, 2)


def test_re2_the_same_configuration_in_three_campaigns_is_one_configuration_even_with_other_runs():
    result = diag([rec(0), rec(1, research_run_id="run_b"), rec(2, research_run_id="run_c", research_run_content_hash=sup.RUN_HASH_2)])
    assert (result.declared_search_config_count, result.multi_campaign_search_config_count, result.declared_strategy_name_count) == (1, 1, 1)
    assert (result.declared_run_reference_count, result.declared_run_id_count, result.multi_campaign_run_reference_count) == (3, 3, 0)


def test_re3_budget_data_and_split_are_not_part_of_the_configuration_identity():
    result = diag([rec(0, budget_per_fold=10, dataset_snapshot_id="a", split_plan_id="x"), rec(1, budget_per_fold=99, dataset_snapshot_id="b", split_plan_id="y")])
    assert (result.declared_search_config_count, result.multi_campaign_search_config_count) == (1, 1)


def test_re4_distinct_strategy_names_are_not_normalised():
    result = diag([rec(0, strategy_name="A"), rec(1, strategy_name="a"), rec(2, strategy_name="a ")])
    assert (result.declared_strategy_name_count, result.declared_search_config_count) == (3, 3)


def test_re5_search_mode_space_and_params_each_change_the_configuration():
    base = [rec(0), rec(1, search_mode="single_var"), rec(2, search_space_hash="ffffffffffff"), rec(3, base_params={"fast": 11, "slow": 30})]
    result = diag(base)
    assert (result.declared_search_config_count, result.declared_strategy_name_count, result.multi_campaign_search_config_count) == (4, 1, 0)


def test_co1_same_run_id_with_two_contents_is_a_conflict_and_a_single_run_id():
    result = diag([rec(0), rec(1, research_run_content_hash=sup.RUN_HASH_2)])
    assert (result.declared_run_reference_count, result.declared_run_id_count) == (2, 1)
    assert (result.id_with_several_content_hashes_count, result.content_hash_with_several_ids_count, result.conflicting_run_id_sample) == (1, 0, ("run_alpha",))


def test_co2_same_content_with_two_ids_is_counted_apart():
    result = diag([rec(0), rec(1, research_run_id="run_forged")])
    assert (result.declared_run_reference_count, result.declared_run_id_count) == (2, 2)
    assert (result.id_with_several_content_hashes_count, result.content_hash_with_several_ids_count, result.conflicting_run_id_sample) == (0, 1, ())


def test_co3_the_conflict_sample_is_sorted_unique_and_capped_while_counts_stay_exact():
    records = []
    for index in range(25):
        records.append(rec(2 * index, research_run_id=f"run_{index:02d}", research_run_content_hash=sup.RUN_HASH_1))
        records.append(rec(2 * index + 1, research_run_id=f"run_{index:02d}", research_run_content_hash=sup.RUN_HASH_2))
    result = diag(records)
    assert result.id_with_several_content_hashes_count == 25 and result.declared_run_id_count == 25 and result.declared_run_reference_count == 50
    assert result.conflicting_run_id_sample == tuple(f"run_{index:02d}" for index in range(20)) and len(result.conflicting_run_id_sample) == pd.MAX_CONFLICT_SAMPLE


def test_ag1_the_result_is_independent_of_the_input_order_and_deterministic():
    records = [rec(0), rec(1, research_run_id="run_b"), rec(2, strategy_name="z"), rec(3)]
    interp, derived, other = sup.world(records)
    first = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    second = pd.diagnose(interp, derived=tuple(reversed(derived)), other_campaign_count=other, max_json_bytes=MAX_JSON)
    third = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert first == second == third and hash(first) == hash(second)


# ── Bases, zéros et absences ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_ba1_a_registry_without_other_campaign_gives_a_constatated_zero_and_none_for_reuse_counts():
    result = pd.diagnose(sup.interpretation([]), derived=(), other_campaign_count=0, max_json_bytes=MAX_JSON)
    assert result.basis is pd.PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN
    assert (result.source_campaign_count, result.unavailable_campaign_count, result.unavailable_breakdown) == (0, 0, ())
    assert (result.declared_run_reference_count, result.declared_run_id_count, result.declared_search_config_count, result.declared_strategy_name_count) == (0, 0, 0, 0)
    assert (result.multi_campaign_run_reference_count, result.multi_campaign_search_config_count, result.id_with_several_content_hashes_count) == (None, None, None)
    assert result.content_hash_with_several_ids_count is None and result.conflicting_run_id_sample == ()


def test_ba2_campaigns_without_any_fact_give_none_never_zero():
    result = pd.diagnose(sup.interpretation([]), derived=(), other_campaign_count=3, max_json_bytes=MAX_JSON)
    assert result.basis is pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ
    assert (result.source_campaign_count, result.unavailable_campaign_count, result.unavailable_breakdown) == (0, 3, (("NO_ATTRIBUTED_ROOT", 3),))
    assert [getattr(result, name) for name in ("declared_run_reference_count", "declared_run_id_count", "declared_search_config_count", "declared_strategy_name_count",
                                                "multi_campaign_run_reference_count", "multi_campaign_search_config_count", "id_with_several_content_hashes_count",
                                                "content_hash_with_several_ids_count")] == [None] * 8


def test_ba3_every_other_campaign_with_a_plan_record_read():
    result = diag([rec(0), rec(1, research_run_id="run_b")])
    assert result.basis is pd.PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ and (result.source_campaign_count, result.unavailable_campaign_count) == (2, 0)


def test_ba4_partial_coverage_gives_lower_bounds_and_names_the_missing_campaigns():
    result = diag([rec(0), rec(1, research_run_id="run_b")], extra_other=3)
    assert result.basis is pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ
    assert (result.source_campaign_count, result.unavailable_campaign_count, result.unavailable_breakdown) == (2, 3, (("NO_ATTRIBUTED_ROOT", 3),))
    assert (result.declared_run_reference_count, result.multi_campaign_run_reference_count) == (2, 0)


def test_ba5_a_single_source_campaign_cannot_compute_reuse_or_conflicts():
    result = diag([rec(0)])
    assert (result.declared_run_reference_count, result.declared_run_id_count, result.declared_search_config_count, result.declared_strategy_name_count) == (1, 1, 1, 1)
    assert (result.multi_campaign_run_reference_count, result.multi_campaign_search_config_count, result.id_with_several_content_hashes_count) == (None, None, None)
    assert result.content_hash_with_several_ids_count is None and result.conflicting_run_id_sample == ()


def test_ba6_the_unavailable_breakdown_adds_defensive_codes_to_the_unattributed_ones():
    broken = rec(1, strategy_name="")
    result = diag([rec(0), broken, rec(2)], extra_other=2)
    assert breakdown(result) == {"NO_ATTRIBUTED_ROOT": 2, "PLAN_FIELD_INVALID": 1} and result.unavailable_breakdown == (("NO_ATTRIBUTED_ROOT", 2), ("PLAN_FIELD_INVALID", 1))
    assert (result.source_campaign_count, result.unavailable_campaign_count) == (2, 3)


# ── Plans manquants, mal formés, hostiles : une campagne indisponible, jamais d'exception ni de compte falsifié ───────────────────────────────────

def only_second_is_broken(second_record=None, **observation_changes):
    records = [rec(0), second_record if second_record is not None else rec(1, research_run_id="run_b"), rec(2, research_run_id="run_c")]
    campaigns = [(f"c{i}", r) for i, r in enumerate(records)]
    observations = [sup.observation(label, r, **(observation_changes if label == "c1" else {})) for label, r in campaigns]
    honest = [(label, {"campaign_id": sup.campaign_record(1)["campaign_id"]} if label == "c1" else r) for label, r in campaigns]          # l'identifiant ATTENDU est celui du plan honnête, jamais celui du plan altéré
    return sup.interpretation(observations), sup.derived_of(honest), 3


def assert_one_unavailable(interp, derived, other, code):
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert (result.source_campaign_count, result.unavailable_campaign_count, result.unavailable_breakdown) == (2, 1, ((code, 1),))
    assert (result.declared_run_reference_count, result.declared_run_id_count) == (2, 2)                       # les deux autres campagnes sont intactes
    assert result.basis is pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ
    return result


@pytest.mark.parametrize("changes", [dict(anomaly="SOME"), dict(value_parsed=False), dict(content_hash=None), dict(kind=EntryKind.DIRECTORY), dict(value=[1, 2]), dict(value="x"), dict(value=None)])
def test_ho1_an_observation_that_b2_would_not_treat_as_strict_leaves_the_campaign_unread(changes):
    assert_one_unavailable(*only_second_is_broken(**changes), "PLAN_RECORD_NOT_READ")


def test_ho2_a_missing_or_duplicated_observation_leaves_the_campaign_unread():
    records = [rec(0), rec(1, research_run_id="run_b"), rec(2, research_run_id="run_c")]
    campaigns = [(f"c{i}", r) for i, r in enumerate(records)]
    missing = sup.interpretation([sup.observation(label, r) for label, r in campaigns if label != "c1"])
    assert_one_unavailable(missing, sup.derived_of(campaigns), 3, "PLAN_RECORD_NOT_READ")
    duplicated = sup.interpretation([sup.observation(label, r) for label, r in campaigns] + [sup.observation("c1", campaigns[1][1])])
    assert_one_unavailable(duplicated, sup.derived_of(campaigns), 3, "PLAN_RECORD_NOT_READ")


def test_ho3_observations_of_another_layout_or_file_name_are_not_the_plan_record():
    records = [rec(0), rec(1, research_run_id="run_b"), rec(2, research_run_id="run_c")]
    campaigns = [(f"c{i}", r) for i, r in enumerate(records)]
    wrong_layout = sup.interpretation([sup.observation(label, r) for label, r in campaigns if label != "c1"], layout=RootLayout.CAMPAIGN_DIR)
    wrong_layout.scans = wrong_layout.scans + (sup.interpretation([sup.observation("c1", campaigns[1][1])], layout=RootLayout.SPLIT_PLAN_DIR).scans[0],)
    assert_one_unavailable(wrong_layout, sup.derived_of(campaigns), 3, "PLAN_RECORD_NOT_READ")
    renamed = sup.interpretation([sup.observation(label, r, relative_path="plan.json.bak" if label == "c1" else "plan.json") for label, r in campaigns])
    assert_one_unavailable(renamed, sup.derived_of(campaigns), 3, "PLAN_RECORD_NOT_READ")


def mutated(index, mutation):
    record = rec(index, research_run_id="run_b")
    mutation(record)
    return record


def drop(key):
    return lambda record: record.pop(key)


FIELD_CASES = {
    "version unknown": lambda r: r.update(campaign_plan_semantics_version="gate_v_campaign_plan_v3"),
    "version absent": drop("campaign_plan_semantics_version"),
    "run id absent": drop("research_run_id"), "strategy absent": drop("strategy_name"), "params absent": drop("base_params"), "mode absent": drop("search_mode"),
    "space absent": drop("search_space_hash"), "hash absent": drop("research_run_content_hash"), "prereg absent": drop("preregistration_id"), "fingerprint absent": drop("campaign_protocol_fingerprint"),
    "strategy int": lambda r: r.update(strategy_name=5), "strategy empty": lambda r: r.update(strategy_name=""), "strategy blank": lambda r: r.update(strategy_name="   "),
    "mode empty": lambda r: r.update(search_mode=""), "mode int": lambda r: r.update(search_mode=1),
    "params empty": lambda r: r.update(base_params={}), "params list": lambda r: r.update(base_params=[1]), "params bool": lambda r: r.update(base_params=True), "params none": lambda r: r.update(base_params=None),
    "hash upper": lambda r: r.update(research_run_content_hash="A" * 64), "hash short": lambda r: r.update(research_run_content_hash="1" * 63), "hash int": lambda r: r.update(research_run_content_hash=1),
    "space 64": lambda r: r.update(search_space_hash="0a" * 32), "space upper": lambda r: r.update(search_space_hash="0A1B2C3D4E5F"), "space 11": lambda r: r.update(search_space_hash="0a1b2c3d4e5"),
    "run id dots": lambda r: r.update(research_run_id="a..b"), "run id slash": lambda r: r.update(research_run_id="a/b"), "run id empty": lambda r: r.update(research_run_id=""),
    "run id bool": lambda r: r.update(research_run_id=True), "prereg upper": lambda r: r.update(preregistration_id="A" * 64),
    "fingerprint short": lambda r: r.update(campaign_protocol_fingerprint="b" * 10),
    "campaign id malformed": lambda r: r.update(campaign_id="gate_v_v2_" + "G" * 64), "campaign id v1 style": lambda r: r.update(campaign_id="camp_1"), "campaign id absent": drop("campaign_id"),
    "nan params": lambda r: r.update(base_params={"x": float("nan")}), "inf params": lambda r: r.update(base_params={"x": float("inf")}),
    "lone surrogate": lambda r: r.update(strategy_name="\ud800"),
    "hash 65 hex": lambda r: r.update(research_run_content_hash="1" * 65), "prereg 65 hex": lambda r: r.update(preregistration_id="a" * 65),
    "fingerprint 65 hex": lambda r: r.update(campaign_protocol_fingerprint="b" * 65), "space 13 hex": lambda r: r.update(search_space_hash="0a1b2c3d4e5f0"),
    "campaign id trailing": lambda r: r.update(campaign_id=r["campaign_id"] + "0"), "run id trailing newline": lambda r: r.update(research_run_id="run_b\n"),
    "run id 256 characters": lambda r: r.update(research_run_id="r" * 256), "mixed key types": lambda r: r.update(base_params={1: "a", "b": 2}),
}


@pytest.mark.parametrize("label", list(FIELD_CASES))
def test_ho4_a_malformed_field_makes_the_campaign_unavailable_with_the_invalid_field_code(label):
    assert_one_unavailable(*only_second_is_broken(mutated(1, FIELD_CASES[label])), "PLAN_FIELD_INVALID")


def test_ho5_identifier_consistency_failures_use_the_dedicated_code():
    wrong_fingerprint = rec(1, research_run_id="run_b")
    wrong_fingerprint["campaign_protocol_fingerprint"] = sup.hex64(0xDEAD)                                       # l'identifiant ne correspond plus aux trois champs
    assert_one_unavailable(*only_second_is_broken(wrong_fingerprint), "PLAN_CAMPAIGN_ID_MISMATCH")
    other_id = rec(1, research_run_id="run_b", campaign_id="gate_v_v2_" + "f" * 64)
    assert_one_unavailable(*only_second_is_broken(other_id), "PLAN_CAMPAIGN_ID_MISMATCH")
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b"))
    swapped = tuple(sorted((label, ("gate_v_v2_" + "e" * 64) if label == "c1" else cid) for label, cid in derived))        # l'identifiant attendu n'est pas celui du plan
    assert_one_unavailable(interp, swapped, other, "PLAN_CAMPAIGN_ID_MISMATCH")


def test_ho6_a_preimage_above_eight_times_the_json_cap_is_refused_with_its_own_code():
    big = rec(1, research_run_id="run_b", base_params={"k": "x" * 400})
    interp, derived, other = only_second_is_broken(big)
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=40)               # plafond de préimage : 320 octets
    assert result.unavailable_breakdown == (("PREIMAGE_TOO_LARGE", 1),) and result.source_campaign_count == 2
    ok = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert ok.unavailable_campaign_count == 0


def config_preimage_size(params) -> int:
    preimage = json.dumps({"base_params": params, "declared_kind": "search_configuration", "identity_version": "declared_search_configuration_v1", "search_mode": "grid",
                           "search_space_hash": sup.SPACE, "strategy_name": "sma_cross"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return len(preimage.encode("utf-8"))


def test_ho7_the_preimage_cap_is_exact_on_the_encoded_size():
    padding = next(n for n in range(100, 164) if config_preimage_size({"k": "x" * n}) % 8 == 0)                      # configuration plus grande que la référence de run des autres campagnes
    params = {"k": "x" * padding}
    size = config_preimage_size(params)
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b", base_params=params))
    exact = size // 8
    assert pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=exact).unavailable_campaign_count == 0                       # taille == plafond : accepté
    refused = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=exact - 1)
    assert refused.unavailable_breakdown == (("PREIMAGE_TOO_LARGE", 1),) and refused.source_campaign_count == 2                                         # une unité de moins : refusé


def test_ho7b_the_cap_counts_encoded_bytes_not_characters():
    params = {"k": "é" * 100}
    characters = len(json.dumps({"base_params": params, "declared_kind": "search_configuration", "identity_version": "declared_search_configuration_v1", "search_mode": "grid",
                                 "search_space_hash": sup.SPACE, "strategy_name": "sma_cross"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
    encoded = config_preimage_size(params)
    assert encoded == characters + 100
    cap_units = (characters + 50) // 8                                                                       # 8 × cap_units est entre le nombre de caractères et le nombre d'octets
    assert characters < 8 * cap_units < encoded
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b", base_params=params))
    assert pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=cap_units).unavailable_breakdown == (("PREIMAGE_TOO_LARGE", 1),)


def test_ho7c_the_cap_also_applies_to_the_run_reference_preimage():
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="r" * 200))                        # configuration petite (environ 230 octets)
    assert config_preimage_size({"fast": 10, "slow": 30}) < 8 * 40
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=40)               # plafond 320 : seule la référence de run (environ 400 octets) le dépasse
    assert result.unavailable_breakdown == (("PREIMAGE_TOO_LARGE", 1),)
    assert pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON).unavailable_campaign_count == 0


@pytest.mark.parametrize("error", [MemoryError("simulated"), RecursionError("simulated")])
def test_ho8_critical_runtime_failures_are_never_degraded_into_an_unavailable_campaign(monkeypatch, error):
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b"))

    def boom(preimage):
        raise error

    monkeypatch.setattr(pd, "_canonical", boom)
    with pytest.raises(type(error)):
        pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)


def test_ho8b_a_deep_parameter_tree_inside_the_scanner_limit_is_counted_normally():
    deep = {"leaf": 1}
    for _ in range(30):                                                                                      # profondeur dans la limite de S1 (32)
        deep = {"n": deep}
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b", base_params=deep))
    assert pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON).unavailable_campaign_count == 0       # la propagation de RecursionError est couverte par ho8 (indépendante de la plateforme)


def test_ho9_an_arithmetic_overflow_is_a_data_failure_with_the_size_code(monkeypatch):
    interp, derived, other = only_second_is_broken(rec(1, research_run_id="run_b", strategy_name="boom_strategy"))
    real = pd._canonical

    def flaky(preimage):
        if preimage.get("strategy_name") == "boom_strategy":
            raise OverflowError("simulated")
        return real(preimage)

    monkeypatch.setattr(pd, "_canonical", flaky)
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert result.unavailable_breakdown == (("PREIMAGE_TOO_LARGE", 1),) and result.source_campaign_count == 2


def test_ho10_the_plan_version_is_checked_before_the_identifier_consistency():
    record = rec(1, research_run_id="run_b", campaign_plan_semantics_version="gate_v_campaign_plan_v1", campaign_id="gate_v_v2_" + "f" * 64)
    assert_one_unavailable(*only_second_is_broken(record), "PLAN_FIELD_INVALID")                              # un contrôle d'identifiant en premier donnerait PLAN_CAMPAIGN_ID_MISMATCH


@pytest.mark.parametrize("run_id", ["v1.2-rc_3", "r" * 255])
def test_ho11_the_run_identifier_charset_accepts_dots_dashes_underscores_and_the_length_limit_is_inclusive(run_id):
    interp, derived, other = only_second_is_broken(rec(1, research_run_id=run_id))
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert result.unavailable_campaign_count == 0 and result.declared_run_id_count == 3


# ── Préconditions : erreurs de programmation, jamais converties en campagne indisponible ───────────────────────────────────────────────────────

def call(interp=None, **kwargs):
    base = dict(derived=(), other_campaign_count=0, max_json_bytes=MAX_JSON)
    base.update(kwargs)
    return pd.diagnose(interp if interp is not None else sup.interpretation([]), **base)


@pytest.mark.parametrize("kwargs,error", [
    (dict(other_campaign_count=True), TypeError), (dict(other_campaign_count=1.0), TypeError), (dict(other_campaign_count="1"), TypeError), (dict(other_campaign_count=-1), ValueError),
    (dict(max_json_bytes=True), TypeError), (dict(max_json_bytes=0), ValueError), (dict(max_json_bytes=-5), ValueError), (dict(max_json_bytes=None), TypeError),
    (dict(derived=[("a", "b")]), TypeError), (dict(derived=("x",)), TypeError), (dict(derived=(("a", "b", "c"),)), TypeError), (dict(derived=((1, "gate_v_v2_" + "a" * 64),), other_campaign_count=1), TypeError),
    (dict(derived=(("a", "bad"),), other_campaign_count=1), ValueError), (dict(derived=(("a", "gate_v_v2_" + "a" * 64 + "0"),), other_campaign_count=1), ValueError),
    (dict(derived=(("a", "gate_v_v2_" + "a" * 64 + "\n"),), other_campaign_count=1), ValueError), (dict(derived=(("a", "gate_v_v2_" + "A" * 64),), other_campaign_count=1), ValueError),
    (dict(derived=(("a", "gate_v_v2_" + "a" * 64), ("a", "gate_v_v2_" + "b" * 64)), other_campaign_count=2), ValueError),
    (dict(derived=(("a", "gate_v_v2_" + "a" * 64), ("b", "gate_v_v2_" + "a" * 64)), other_campaign_count=2), ValueError),
    (dict(derived=(("a", "gate_v_v2_" + "a" * 64),), other_campaign_count=0), ValueError),
])
def test_pr1_invalid_arguments_raise_before_any_index_or_loop(kwargs, error):
    class Exploding:
        @property
        def scans(self):
            raise AssertionError("l'interprétation ne doit pas être lue avant les préconditions")
    with pytest.raises(error):
        call(Exploding(), **kwargs)


def test_pr2_the_signature_has_no_default_for_the_cap_and_is_keyword_only():
    signature = inspect.signature(pd.diagnose)
    assert [p.kind.name for p in signature.parameters.values()] == ["POSITIONAL_OR_KEYWORD", "KEYWORD_ONLY", "KEYWORD_ONLY", "KEYWORD_ONLY"]
    assert all(p.default is inspect.Parameter.empty for p in signature.parameters.values())
    assert [p for p in signature.parameters] == ["interpretation", "derived", "other_campaign_count", "max_json_bytes"]


# ── Bornes : un seul parcours de S1, sorties bornées ──────────────────────────────────────────────────────────────────────────────────────────

def test_bo1_the_observations_are_walked_once_whatever_the_number_of_campaigns():
    records = [rec(index, research_run_id=f"run_{index}") for index in range(300)]
    sup.CountingList.passes = 0
    interp, derived, other = sup.world(records, counting=True)
    result = pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert sup.CountingList.passes == 1 and result.declared_run_reference_count == 300


def test_bo2_outputs_are_bounded_even_with_20000_synthetic_facts():
    records = [rec(index, research_run_id=f"run_{index % 40}", research_run_content_hash=sup.hex64(index % 7 + 1)) for index in range(20000)]
    result = diag(records)
    assert result.source_campaign_count == 20000 and len(result.conflicting_run_id_sample) <= pd.MAX_CONFLICT_SAMPLE and len(result.unavailable_breakdown) <= len(pd.UNAVAILABLE_CODES)
    assert (result.declared_run_reference_count, result.declared_run_id_count, result.id_with_several_content_hashes_count, result.content_hash_with_several_ids_count) == (280, 40, 40, 7)
    assert result.declared_search_config_count == 1 and result.multi_campaign_search_config_count == 1 and result.multi_campaign_run_reference_count == 280


def test_bo3_the_breakdown_never_has_more_than_five_pairs_and_is_sorted():
    result = diag([rec(0), rec(1, strategy_name=""), rec(2, campaign_id="gate_v_v2_" + "f" * 64), rec(3, search_mode=""), rec(4)], extra_other=1)
    assert [code for code, _n in result.unavailable_breakdown] == sorted(code for code, _n in result.unavailable_breakdown) and len(result.unavailable_breakdown) <= 5


# ── Non-promotion : constantes, vocabulaire, absence de verdict ───────────────────────────────────────────────────────────────────────────────

NOT_ESTABLISHED = ("EXECUTION_OF_DECLARED_RESEARCH", "EVALUATED_PARAMETER_POINTS", "V1_CAMPAIGNS", "CAMPAIGNS_OUTSIDE_REGISTRY", "RESEARCH_OUTSIDE_CAMPAIGNS", "RUN_ARTIFACT_VERIFICATION",
                   "RUN_REFERENCE_AUTHENTICITY", "PLAN_SOURCES_CROSS_VALIDATION", "PLAN_ROOT_CONTENT_ATTRIBUTION", "STRATEGY_CODE_IDENTITY", "CONFIGURATION_DATA_BINDING", "OWN_CAMPAIGN_OVERLAP",
                   "ABANDONED_FAILED_OR_VOID_ATTEMPTS", "MULTIPLE_TESTING_N")


def test_np1_constant_properties_are_the_documented_literals():
    result = diag([rec(0)])
    assert (result.semantics_version, result.scope, result.not_established) == ("gate_v_plan_declared_v1", "REGISTRY_CHAIN_PLAN_V2_ONLY", NOT_ESTABLISHED)
    assert len(NOT_ESTABLISHED) == 14
    for name in ("semantics_version", "scope", "not_established"):
        assert name not in {f.name for f in dataclasses.fields(pd.PlanDeclaredDiagnostic)}
        with pytest.raises(TypeError):
            pd.PlanDeclaredDiagnostic(basis=result.basis, **{f.name: getattr(result, f.name) for f in dataclasses.fields(result) if f.name != "basis"}, **{name: "x"})


FORBIDDEN_SUBSTRINGS = ("FRESH", "NO_OVERLAP", "ADMIT", "ADMISSION", "CLAIM", "AUTHORI", "ABSENCE_ESTABLISHED", "EXCLUSION")
FORBIDDEN_TOKENS = {"PASS", "OK", "VALID", "CLEAN", "CLEARED", "ALLOWED", "GRANTED", "ACCESS"}
FORBIDDEN_WORDS = {"TRIAL", "TRIALS", "TOTAL", "COMPLETE", "OVERALL", "GLOBAL", "ALL", "INVENTORY", "VERDICT", "SCORE"}


def public_vocabulary():
    names = list(pd.__all__) + [f.name for f in dataclasses.fields(pd.PlanDeclaredDiagnostic)] + list(pd.UNAVAILABLE_CODES) + list(NOT_ESTABLISHED)
    names += [member.name for member in pd.PlanDeclaredBasis] + [member.value for member in pd.PlanDeclaredBasis]
    names += [name for name, value in inspect.getmembers(pd.PlanDeclaredDiagnostic) if isinstance(value, property)]
    return names


def test_np2_vocabulary_of_names_codes_enumerations_fields_and_properties():
    names = public_vocabulary()
    assert len(names) > 40                                                                                   # témoin de non-vacuité de la collecte
    for name in names:
        upper = name.upper()
        assert not any(bad in upper for bad in FORBIDDEN_SUBSTRINGS), name
        assert not (FORBIDDEN_TOKENS | FORBIDDEN_WORDS) & set(upper.split("_")), name
    assert any(bad in "FRESH_X" for bad in FORBIDDEN_SUBSTRINGS) and FORBIDDEN_WORDS & set("ALL_X".split("_"))        # témoin : la garde détecterait un mot interdit


def test_np3_the_type_has_no_boolean_verdict_no_serialisation_and_no_copyable_digest():
    members = {name for name, _ in inspect.getmembers(pd.PlanDeclaredDiagnostic) if not name.startswith("_")}
    assert not {name for name in members if re.match(r"(to_|from_|canonical|serial|digest|fingerprint|hash)", name)}
    assert not any(isinstance(getattr(pd.PlanDeclaredDiagnostic, name, None), property) and name in ("ok", "valid", "complete", "passed") for name in members)
    result = diag([rec(0)])
    assert all(type(getattr(result, f.name)) is not bool for f in dataclasses.fields(result))


def test_np4_the_diagnostic_and_its_inputs_are_not_mutated():
    records = [rec(0), rec(1, research_run_id="run_b")]
    snapshot = json.dumps(records, sort_keys=True)
    interp, derived, other = sup.world(records)
    pd.diagnose(interp, derived=derived, other_campaign_count=other, max_json_bytes=MAX_JSON)
    assert json.dumps(records, sort_keys=True) == snapshot
    with pytest.raises(dataclasses.FrozenInstanceError):
        diag(records).basis = pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ


# ── Invariants du constructeur ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

GOOD = dict(basis=pd.PlanDeclaredBasis.EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, source_campaign_count=3, unavailable_campaign_count=0, unavailable_breakdown=(),
            declared_run_reference_count=2, declared_run_id_count=2, declared_search_config_count=2, declared_strategy_name_count=1, multi_campaign_run_reference_count=1,
            multi_campaign_search_config_count=1, id_with_several_content_hashes_count=0, content_hash_with_several_ids_count=0, conflicting_run_id_sample=())


def build(**changes):
    return pd.PlanDeclaredDiagnostic(**{**GOOD, **changes})


K4 = dict(source_campaign_count=4, declared_run_reference_count=4, declared_run_id_count=2, declared_search_config_count=2, id_with_several_content_hashes_count=2,
          conflicting_run_id_sample=("a", "b"), multi_campaign_run_reference_count=0, multi_campaign_search_config_count=1)


EQUALITIES = dict(source_campaign_count=4, declared_run_reference_count=2, declared_run_id_count=2, declared_search_config_count=2, declared_strategy_name_count=1,
                  multi_campaign_run_reference_count=2, multi_campaign_search_config_count=2, id_with_several_content_hashes_count=0, content_hash_with_several_ids_count=1,
                  conflicting_run_id_sample=())


def test_iv0_the_reference_constructions_are_valid():
    assert build().source_campaign_count == 3
    assert build(**K4).conflicting_run_id_sample == ("a", "b")
    assert build(**EQUALITIES).multi_campaign_run_reference_count == 2                                         # toutes les bornes à l'égalité : accepté


@pytest.mark.parametrize("label,changes", [
    ("basis not an enum", dict(basis="EVERY_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ")),
    ("more references than run ids without any id conflict", dict(declared_run_reference_count=3, multi_campaign_run_reference_count=0)),
    ("bool as count", dict(source_campaign_count=True)), ("bool unavailable count", dict(unavailable_campaign_count=False)), ("bool names", dict(declared_strategy_name_count=True)),
    ("bool conflict count", dict(id_with_several_content_hashes_count=False)), ("run ids zero", dict(declared_run_id_count=0)), ("negative count", dict(unavailable_campaign_count=-1)), ("float count", dict(declared_run_reference_count=2.0)),
    ("breakdown list", dict(unavailable_breakdown=[])), ("sample list", dict(conflicting_run_id_sample=[])),
    ("EVERY with unavailable", dict(unavailable_campaign_count=1, unavailable_breakdown=(("PLAN_FIELD_INVALID", 1),))),
    ("EVERY with k = 0", dict(source_campaign_count=0, declared_run_reference_count=0)),
    ("SOME with u = 0", dict(basis=pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ)),
    ("NO with k > 0", dict(basis=pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, unavailable_campaign_count=1, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 1),))),
    ("EMPTY with k > 0", dict(basis=pd.PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN)),
    ("references above k", dict(declared_run_reference_count=4)), ("references zero", dict(declared_run_reference_count=0)), ("run ids above references", dict(declared_run_id_count=3)),
    ("configs above k", dict(declared_search_config_count=4)), ("names above configs", dict(declared_strategy_name_count=3)), ("names zero", dict(declared_strategy_name_count=0)),
    ("multi runs too many", dict(multi_campaign_run_reference_count=2)), ("multi configs too many", dict(multi_campaign_search_config_count=2)),
    ("multi missing for k >= 2", dict(multi_campaign_run_reference_count=None)), ("conflict missing for k >= 2", dict(id_with_several_content_hashes_count=None)),
    ("three id conflicts with two run ids", dict(id_with_several_content_hashes_count=3, conflicting_run_id_sample=("a", "b", "c"))),
    ("id conflicts above half the references", dict(declared_run_id_count=2, id_with_several_content_hashes_count=2, conflicting_run_id_sample=("a", "b"))),
    ("hash conflicts above half references", dict(content_hash_with_several_ids_count=2)),
    ("sample wrong length", dict(id_with_several_content_hashes_count=1, conflicting_run_id_sample=())),
    ("sample unsorted", {**K4, "conflicting_run_id_sample": ("b", "a")}),
    ("sample duplicated", {**K4, "conflicting_run_id_sample": ("a", "a")}),
    ("sample too short", {**K4, "conflicting_run_id_sample": ("a",)}),
    ("sample entry too long", {**K4, "conflicting_run_id_sample": ("a", "b" * 256)}),
    ("multi runs above references", dict(declared_run_reference_count=1, declared_run_id_count=1, multi_campaign_run_reference_count=2)),
    ("references plus reused above k", dict(multi_campaign_run_reference_count=2, declared_run_reference_count=2)),
    ("configs plus reused above k", dict(multi_campaign_search_config_count=2, declared_search_config_count=2)),
    ("multi configs above configs", dict(declared_search_config_count=1, declared_strategy_name_count=1, multi_campaign_search_config_count=2)),
    ("id conflicts without a distinct id", {**K4, "declared_run_id_count": 4, "id_with_several_content_hashes_count": 1, "conflicting_run_id_sample": ("a",)}),
    ("ids equal references yet id conflict", dict(id_with_several_content_hashes_count=1, conflicting_run_id_sample=("a",), declared_run_reference_count=2, declared_run_id_count=2)),
    ("ids above references minus conflicts", {**K4, "declared_run_id_count": 3, "id_with_several_content_hashes_count": 2}),
    ("hash conflict with a single id", dict(declared_run_reference_count=2, declared_run_id_count=1, id_with_several_content_hashes_count=1, conflicting_run_id_sample=("a",), content_hash_with_several_ids_count=1)),
    ("sample not strings", {**K4, "conflicting_run_id_sample": ("a", 1)}),
    ("id conflicts above run ids", {**K4, "declared_run_id_count": 1, "id_with_several_content_hashes_count": 2}),
])
def test_iv1_inconsistent_constructions_are_refused(label, changes):
    with pytest.raises(ValueError):
        build(**changes)


def test_iv2_the_breakdown_is_a_closed_sorted_unique_positive_vocabulary_summing_to_the_unavailable_count():
    valid = dict(basis=pd.PlanDeclaredBasis.SOME_CHAIN_CAMPAIGNS_HAVE_PLAN_RECORD_READ, unavailable_campaign_count=3)
    build(**valid, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 2), ("PLAN_FIELD_INVALID", 1)))
    for bad in ((("PLAN_FIELD_INVALID", 1), ("NO_ATTRIBUTED_ROOT", 2)), (("NO_ATTRIBUTED_ROOT", 3), ("NO_ATTRIBUTED_ROOT", 0)), (("NO_ATTRIBUTED_ROOT", 2),), (("UNKNOWN", 3),),
                (("NO_ATTRIBUTED_ROOT", 2), ("PLAN_FIELD_INVALID", 2)), (("NO_ATTRIBUTED_ROOT", True), ("PLAN_FIELD_INVALID", 2)), ((1, 3),), (("NO_ATTRIBUTED_ROOT", 0), ("PLAN_FIELD_INVALID", 3)),
                (("NO_ATTRIBUTED_ROOT", 3, 0),), ("x",)):
        with pytest.raises(ValueError):
            build(**valid, unavailable_breakdown=bad)


def test_iv3_the_no_data_and_empty_registry_shapes_are_the_only_ones_with_none_or_zero_declared_counts():
    nothing = dict(declared_run_reference_count=None, declared_run_id_count=None, declared_search_config_count=None, declared_strategy_name_count=None, multi_campaign_run_reference_count=None,
                   multi_campaign_search_config_count=None, id_with_several_content_hashes_count=None, content_hash_with_several_ids_count=None, conflicting_run_id_sample=())
    build(basis=pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, source_campaign_count=0, unavailable_campaign_count=2, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 2),), **nothing)
    with pytest.raises(ValueError):
        build(basis=pd.PlanDeclaredBasis.NO_CHAIN_CAMPAIGN_HAS_PLAN_RECORD_READ, source_campaign_count=0, unavailable_campaign_count=2, unavailable_breakdown=(("NO_ATTRIBUTED_ROOT", 2),),
              **{**nothing, "declared_run_reference_count": 0})
    empty = {**nothing, "declared_run_reference_count": 0, "declared_run_id_count": 0, "declared_search_config_count": 0, "declared_strategy_name_count": 0}
    build(basis=pd.PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN, source_campaign_count=0, unavailable_campaign_count=0, unavailable_breakdown=(), **empty)
    with pytest.raises(ValueError):
        build(basis=pd.PlanDeclaredBasis.REGISTRY_HAS_NO_OTHER_CAMPAIGN, source_campaign_count=0, unavailable_campaign_count=0, unavailable_breakdown=(), **{**empty, "declared_run_id_count": None})


def test_iv4_a_single_source_campaign_requires_none_for_reuse_counts():
    one = dict(source_campaign_count=1, declared_run_reference_count=1, declared_run_id_count=1, declared_search_config_count=1, declared_strategy_name_count=1, multi_campaign_run_reference_count=None,
               multi_campaign_search_config_count=None, id_with_several_content_hashes_count=None, content_hash_with_several_ids_count=None, conflicting_run_id_sample=())
    build(**one)
    with pytest.raises(ValueError):
        build(**{**one, "multi_campaign_run_reference_count": 0})


# ── Garde statique du module : pur, aucun disque, aucun nom interdit ──────────────────────────────────────────────────────────────────────────

TREE = ast.parse(SOURCE)
NAMES = {n.id for n in ast.walk(TREE) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(TREE) if isinstance(n, ast.Attribute)}


def imports():
    found = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


def test_gu1_imports_are_the_documented_allowlist_and_nothing_dynamic():
    assert imports() <= {"__future__", "dataclasses", "enum", "hashlib", "json", "re", "typing", "gate_v_campaign_plan_v2", "gate_v_exposure_interpreters", "gate_v_exposure_scan"}, imports()
    assert not {"__import__", "importlib", "import_module", "eval", "exec"} & NAMES
    from_imports = {a.name for n in ast.walk(TREE) if isinstance(n, ast.ImportFrom) and n.module == "gate_v_campaign_plan_v2" for a in n.names}
    assert from_imports <= {"GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION", "compute_gate_v_campaign_id_v2"}, from_imports


def test_gu2_no_disk_clock_random_process_or_network_primitive():
    calls = {n.func.id for n in ast.walk(TREE) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert not {"open", "print", "input"} & calls
    assert not {"os", "pathlib", "subprocess", "time", "random", "shutil", "tempfile", "socket", "urllib", "datetime", "sys"} & (imports() | NAMES)
    assert not {"write", "write_bytes", "write_text", "mkdir", "unlink", "rename", "replace", "remove", "rmdir", "makedirs", "utime", "now", "time", "popen", "system", "run"} & NAMES


def test_gu3_the_module_names_none_of_the_forbidden_modules_functions_or_writers():
    for forbidden in ("gate_v_audit_protocol", "gate_v_exposure_interpreters_v", "interpret_audit_roots", "save_exclusive", "save_atomic", "load_json_tolerant", "publish_", "subprocess", "datetime",
                      "initialize_synthetic_registry", "assemble_record", "gate_v_registry", "gate_v_exposure_store", "gate_v_exposure_declarations", "gate_v_inventory_preconditions",
                      "gate_v_campaign_manifest", "gate_v_final_holdout", "pandas", "read_csv", "nasdaq_3m", "FINAL_HOLDOUT"):
        assert forbidden not in SOURCE, forbidden
    assert not re.search(r"gate_v_k1s2_(verifier|observations|emptiness)", SOURCE)


def test_gu4_no_global_mutable_state_beyond_closed_constants():
    assignments = [node for node in TREE.body if isinstance(node, ast.Assign)]
    for node in assignments:
        if [t.id for t in node.targets if isinstance(t, ast.Name)] == ["__all__"]:
            continue
        assert not isinstance(node.value, (ast.List, ast.Dict, ast.Set)), ast.dump(node)[:120]


def test_pb1_every_aggregation_of_diagnose_satisfies_the_constructor_invariants():
    import random
    generator = random.Random(20261106)
    runs = [("run_a", sup.RUN_HASH_1), ("run_a", sup.RUN_HASH_2), ("run_b", sup.RUN_HASH_1), ("run_b", sup.RUN_HASH_2), ("run_c", sup.hex64(3)), ("run_d", sup.hex64(3))]
    configs = [("s1", {"x": 1}, "grid"), ("s1", {"x": 2}, "grid"), ("s2", {"x": 1}, "grid"), ("s1", {"x": 1}, "single_var")]
    for trial in range(400):
        count = generator.randint(1, 7)
        records = []
        for index in range(count):
            run_id, content = generator.choice(runs)
            strategy, params, mode = generator.choice(configs)
            records.append(rec(index, research_run_id=run_id, research_run_content_hash=content, strategy_name=strategy, base_params=params, search_mode=mode))
        result = diag(records, extra_other=generator.randint(0, 2))                                          # le constructeur valide chaque résultat ; une violation lèverait ici
        assert result.source_campaign_count == count, trial
