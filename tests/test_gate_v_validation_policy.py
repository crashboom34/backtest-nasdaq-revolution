"""
tests/test_gate_v_validation_policy.py — AF-V-07 Slice A : GateVValidationPolicyVersion.

Typed scientific criteria (OOS/Walk-Forward/Monte-Carlo/Parameter Stability), canonical
semantic hash, immutable persistence — ADR 0025 Décision 4/5/14. NO evaluator, NO real
threshold policy, NO PreRegistration/Plan V2/Claim/OOS wrapper/Assessment here (later
slices). Synthetic values only, no market data.
"""

from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import FrozenInstanceError

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gate_v_validation_policy import (
    REQUIRED_VALIDATION_TYPES,
    GateVValidationPolicyVersion,
    MonteCarloPolicyCriterion,
    OosPolicyCriterion,
    ParameterStabilityPolicyCriterion,
    WalkForwardPolicyCriterion,
    build_gate_v_validation_policy,
    canonical_policy_json,
    load_gate_v_validation_policy,
    policy_content_hash,
    save_gate_v_validation_policy,
)


def _oos(**kwargs):
    kwargs.setdefault("metric", "net_ret_pct")
    kwargs.setdefault("operator", ">")
    kwargs.setdefault("threshold", 0.0)
    return OosPolicyCriterion(**kwargs)


def _wf(**kwargs):
    kwargs.setdefault("metric", "oos_net_return_pct")
    kwargs.setdefault("operator", ">")
    kwargs.setdefault("threshold", 0.0)
    return WalkForwardPolicyCriterion(**kwargs)


def _mc(**kwargs):
    kwargs.setdefault("distribution", "sampling_uncertainty_net_ret_pct")
    kwargs.setdefault("percentile", "p5")
    kwargs.setdefault("operator", ">")
    kwargs.setdefault("threshold", 0.0)
    return MonteCarloPolicyCriterion(**kwargs)


def _ps(**kwargs):
    kwargs.setdefault("scope", "ALL_USABLE_PARAMETERS")
    kwargs.setdefault("metric", "degradation_by_param")
    kwargs.setdefault("operator", "<")
    kwargs.setdefault("threshold", 1.0)
    return ParameterStabilityPolicyCriterion(**kwargs)


def _full_criteria():
    return {
        "oos": (_oos(),),
        "walk_forward": (_wf(),),
        "monte_carlo": (_mc(),),
        "parameter_stability": (_ps(),),
    }


def _policy(policy_id="pol_test", criteria=None):
    return build_gate_v_validation_policy(policy_id, criteria if criteria is not None else _full_criteria())


# A — REQUIRED_VALIDATION_TYPES exact tuple.
def test_required_validation_types_exact_tuple():
    assert REQUIRED_VALIDATION_TYPES == ("oos", "walk_forward", "monte_carlo", "parameter_stability")


# B — valid construction per criterion type.
def test_valid_construction_each_criterion_type():
    assert _oos().metric == "net_ret_pct"
    assert _wf().metric == "oos_net_return_pct"
    assert _mc().distribution == "sampling_uncertainty_net_ret_pct"
    assert _ps().scope == "ALL_USABLE_PARAMETERS"


# C — invalid metric rejected per family.
def test_invalid_metric_rejected_oos():
    with pytest.raises(ValueError):
        _oos(metric="not_a_real_metric")


def test_invalid_metric_rejected_walk_forward():
    with pytest.raises(ValueError):
        _wf(metric="not_a_real_metric")


def test_invalid_metric_rejected_parameter_stability():
    with pytest.raises(ValueError):
        _ps(metric="not_a_real_metric")


# D — invalid operator rejected.
def test_invalid_operator_rejected():
    with pytest.raises(ValueError):
        _oos(operator="!=")


# E — invalid MC percentile rejected.
def test_invalid_mc_percentile_rejected():
    with pytest.raises(ValueError):
        _mc(percentile="p99")


# F — invalid MC distribution rejected.
def test_invalid_mc_distribution_rejected():
    with pytest.raises(ValueError):
        _mc(distribution="not_a_real_distribution")


# G — invalid PS scope rejected.
def test_invalid_ps_scope_rejected():
    with pytest.raises(ValueError):
        _ps(scope="WORST_PARAM_NAMED_RSI")


# H — invalid PS metric rejected.
def test_invalid_ps_metric_rejected():
    with pytest.raises(ValueError):
        _ps(metric="not_a_real_metric")


# I — NaN/Inf rejected.
def test_nan_threshold_rejected():
    with pytest.raises(ValueError):
        _oos(threshold=math.nan)


def test_inf_threshold_rejected():
    with pytest.raises(ValueError):
        _oos(threshold=math.inf)


def test_neg_inf_threshold_rejected():
    with pytest.raises(ValueError):
        _oos(threshold=-math.inf)


# J — bool threshold rejected (bool-is-int must not silently pass).
def test_bool_threshold_rejected():
    with pytest.raises(ValueError):
        _oos(threshold=True)
    with pytest.raises(ValueError):
        _oos(threshold=False)


# C (extra) — string threshold rejected (type check, not just numeric range).
def test_string_threshold_rejected():
    with pytest.raises(ValueError):
        _oos(threshold="0.5")


# K — unknown scientific_criteria validation-type key rejected.
def test_unknown_validation_type_key_rejected():
    with pytest.raises(ValueError):
        build_gate_v_validation_policy("pol_bad_key", {"champion": (_oos(),)})


# L — wrong criterion class under a validation family rejected.
def test_wrong_criterion_class_under_family_rejected():
    with pytest.raises(ValueError):
        build_gate_v_validation_policy("pol_bad_class", {"oos": (_wf(),)})


# M — effective immutability.
def test_criterion_is_frozen():
    criterion = _oos()
    with pytest.raises(FrozenInstanceError):
        criterion.metric = "profit_factor"


def test_policy_is_frozen():
    policy = _policy()
    with pytest.raises(FrozenInstanceError):
        policy.validation_policy_id = "other"


def test_scientific_criteria_mapping_rejects_item_assignment():
    policy = _policy()
    with pytest.raises(TypeError):
        policy.scientific_criteria["oos"] = ()


def test_scientific_criteria_family_is_tuple_not_list():
    policy = _policy()
    assert isinstance(policy.scientific_criteria["oos"], tuple)


# N — pass_capable cases 0/4, 1/4, 3/4, 4/4.
def test_pass_capable_zero_of_four():
    policy = _policy(criteria={})
    assert policy.pass_capable is False


def test_pass_capable_one_of_four():
    policy = _policy(criteria={"oos": (_oos(),)})
    assert policy.pass_capable is False


def test_pass_capable_three_of_four():
    criteria = _full_criteria()
    del criteria["parameter_stability"]
    policy = _policy(criteria=criteria)
    assert policy.pass_capable is False


def test_pass_capable_four_of_four():
    policy = _policy()
    assert policy.pass_capable is True


def test_pass_capable_empty_tuple_family_not_capable():
    criteria = _full_criteria()
    criteria["monte_carlo"] = ()
    policy = _policy(criteria=criteria)
    assert policy.pass_capable is False


# O — canonical hash deterministic.
def test_hash_deterministic():
    policy = _policy()
    assert policy_content_hash(policy) == policy_content_hash(policy)
    other = _policy()
    assert policy_content_hash(policy) == policy_content_hash(other)


# P — hash unaffected by serialization formatting/key order.
def test_hash_unaffected_by_manual_key_reordering():
    policy = _policy()
    canonical = canonical_policy_json(policy)
    reordered_record = json.loads(canonical)
    reordered = {
        "scientific_criteria": reordered_record["scientific_criteria"],
        "validation_policy_id": reordered_record["validation_policy_id"],
    }
    reordered_json = json.dumps(reordered, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    reordered_hash = __import__("hashlib").sha256(reordered_json.encode("utf-8")).hexdigest()
    assert reordered_hash == policy_content_hash(policy)


# Q — hash changes on normative content change.
def test_hash_changes_on_threshold_change():
    policy_a = _policy(criteria={"oos": (_oos(threshold=0.0),)})
    policy_b = _policy(criteria={"oos": (_oos(threshold=1.0),)})
    assert policy_content_hash(policy_a) != policy_content_hash(policy_b)


def test_hash_changes_on_policy_id_change():
    policy_a = _policy(policy_id="pol_a")
    policy_b = _policy(policy_id="pol_b")
    assert policy_content_hash(policy_a) != policy_content_hash(policy_b)


def test_int_and_float_threshold_hash_identically():
    policy_int = _policy(criteria={"oos": (_oos(threshold=1),)})
    policy_float = _policy(criteria={"oos": (_oos(threshold=1.0),)})
    assert policy_content_hash(policy_int) == policy_content_hash(policy_float)


# R — criterion-ordering behavior deterministic and explicitly tested (never sorted).
def test_criterion_order_is_normative_not_sorted():
    forward = _policy(criteria={"oos": (_oos(threshold=5.0), _oos(threshold=1.0))})
    reversed_order = _policy(criteria={"oos": (_oos(threshold=1.0), _oos(threshold=5.0))})
    assert policy_content_hash(forward) != policy_content_hash(reversed_order)


# S — save/load typed round-trip.
def test_save_load_round_trip_preserves_typed_criteria(tmp_path):
    policy = _policy()
    path = tmp_path / "pol_test.json"
    save_gate_v_validation_policy(path, policy)
    loaded = load_gate_v_validation_policy(path)
    assert loaded.validation_policy_id == policy.validation_policy_id
    assert isinstance(loaded.scientific_criteria["oos"][0], OosPolicyCriterion)
    assert isinstance(loaded.scientific_criteria["walk_forward"][0], WalkForwardPolicyCriterion)
    assert isinstance(loaded.scientific_criteria["monte_carlo"][0], MonteCarloPolicyCriterion)
    assert isinstance(loaded.scientific_criteria["parameter_stability"][0], ParameterStabilityPolicyCriterion)
    assert policy_content_hash(loaded) == policy_content_hash(policy)


# T — immutable persistence refuses overwrite.
def test_save_refuses_overwrite(tmp_path):
    policy = _policy()
    path = tmp_path / "pol_test.json"
    save_gate_v_validation_policy(path, policy)
    with pytest.raises(FileExistsError):
        save_gate_v_validation_policy(path, policy)


# U — malformed persisted record rejected/fails closed under strict load.
def test_load_rejects_missing_file(tmp_path):
    with pytest.raises(ValueError):
        load_gate_v_validation_policy(tmp_path / "does_not_exist.json")


def test_load_rejects_missing_required_field(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text(json.dumps({"validation_policy_id": "pol_x"}), encoding="utf-8")
    with pytest.raises(ValueError):
        load_gate_v_validation_policy(path)


def test_load_rejects_unknown_family_key(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text(
        json.dumps({"validation_policy_id": "pol_x", "scientific_criteria": {"champion": []}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gate_v_validation_policy(path)


def test_load_rejects_unknown_top_level_key(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text(
        json.dumps(
            {
                "validation_policy_id": "pol_x",
                "scientific_criteria": {},
                "unexpected_field": "smuggled",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gate_v_validation_policy(path)


def test_load_rejects_malformed_criterion(tmp_path):
    path = tmp_path / "malformed.json"
    path.write_text(
        json.dumps(
            {
                "validation_policy_id": "pol_x",
                "scientific_criteria": {"oos": [{"metric": "net_ret_pct", "operator": ">"}]},
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_gate_v_validation_policy(path)


# V — invalid validation_policy_id rejected.
def test_invalid_validation_policy_id_empty_rejected():
    with pytest.raises(ValueError):
        build_gate_v_validation_policy("", _full_criteria())


def test_invalid_validation_policy_id_path_separator_rejected():
    with pytest.raises(ValueError):
        build_gate_v_validation_policy("pol/../escape", _full_criteria())


def test_invalid_validation_policy_id_disallowed_char_rejected():
    with pytest.raises(ValueError):
        build_gate_v_validation_policy("pol:bad", _full_criteria())


# W — persisted representation does not leak derived/forbidden fields.
def test_persisted_record_excludes_derived_and_forbidden_fields(tmp_path):
    policy = _policy()
    path = tmp_path / "pol_test.json"
    save_gate_v_validation_policy(path, policy)
    raw = json.loads(path.read_text(encoding="utf-8"))
    forbidden = {
        "pass_capable",
        "treatment_of_inconclusive",
        "required_validation_types",
        "strategy_name",
        "policy_content_hash",
        "created_at",
    }
    assert forbidden.isdisjoint(raw.keys())
    assert set(raw.keys()) == {"validation_policy_id", "scientific_criteria"}
