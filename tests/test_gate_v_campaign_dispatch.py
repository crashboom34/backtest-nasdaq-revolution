"""
tests/test_gate_v_campaign_dispatch.py — AF-V-07 Slice D6 (ADR 0025 Décision 21.9 / 21.11 / 21.13).

`classify_gate_v_campaign_dir(campaign_dir) -> "v1" | "v2"` : façade de CLASSIFICATION en lecture seule. Elle lit au
plus `plan.json` puis `manifest.json`, discrimine V1/V2 par le CONTENU (jamais par le nom du dossier, simple contrôle
de cohérence), ne valide aucune science, ne charge aucune preuve, n'exécute rien et n'accorde aucun droit
FINAL_HOLDOUT. Les enregistrements des tests sont des records MINIMAUX écrits à la main : D6 ne teste que la
discrimination, pas la chargeabilité scientifique par les chargeurs V1/V2.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import gate_v_campaign_dispatch as d6

V1_ID = "gate_v_" + "ab" * 32
V2_ID = "gate_v_v2_" + "cd" * 32
PLAN_V2 = "gate_v_campaign_plan_v2"
MANIFEST_V2 = "gate_v_campaign_manifest_v2"
Error = d6.GateVCampaignDiscriminationError


# ============================================================================================
# Fabrication de dossiers de campagne minimaux
# ============================================================================================


def v1_plan(campaign_id=V1_ID, **extra):
    return {"campaign_id": campaign_id, "research_run_id": "research_synthetic", **extra}


def v2_plan(campaign_id=V2_ID, **extra):
    return {"campaign_plan_semantics_version": PLAN_V2, "campaign_id": campaign_id, **extra}


def v1_manifest(campaign_id=V1_ID, **extra):
    return {"campaign_id": campaign_id, "status": "READY_FOR_EXECUTION", **extra}


def v2_manifest(campaign_id=V2_ID, **extra):
    return {"manifest_semantics_version": MANIFEST_V2, "campaign_id": campaign_id, "manifest_revision": 0, **extra}


def campaign(tmp_path, *, plan, manifest=None, name=None, label="c"):
    """Dossier `tmp_path/<label>/<name>` ; `plan`/`manifest` : dict (JSON), str/bytes (contenu brut) ou `None`
    (fichier absent). Par défaut le dossier porte le `campaign_id` du plan, comme une vraie campagne."""
    if name is None:
        name = plan.get("campaign_id", V1_ID) if isinstance(plan, dict) and isinstance(
            plan.get("campaign_id"), str) else V1_ID
    directory = tmp_path / label / name
    directory.mkdir(parents=True)
    for filename, content in (("plan.json", plan), ("manifest.json", manifest)):
        if content is None:
            continue
        if isinstance(content, (str, bytes)):
            (directory / filename).write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        else:
            (directory / filename).write_text(json.dumps(content), encoding="utf-8")
    return directory


# ============================================================================================
# Tranche 1 — API publique et cas nominaux (§21.9 : plan seul, puis plan + manifest cohérent)
# ============================================================================================


def test_the_public_surface_is_exactly_the_error_and_the_classifier():
    assert set(d6.__all__) == {"GateVCampaignDiscriminationError", "classify_gate_v_campaign_dir"}
    assert issubclass(d6.GateVCampaignDiscriminationError, ValueError)
    public = {name for name in dir(d6) if not name.startswith("_") and getattr(d6.__dict__[name], "__module__", None)
              == d6.__name__}
    assert public == {"GateVCampaignDiscriminationError", "classify_gate_v_campaign_dir"}


def test_a_v1_plan_without_a_manifest_is_v1(tmp_path):
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan())) == "v1"


def test_a_v2_plan_without_a_manifest_is_v2(tmp_path):
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v2_plan())) == "v2"


def test_a_v1_plan_with_a_coherent_v1_manifest_is_v1(tmp_path):
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan(), manifest=v1_manifest())) == "v1"


def test_a_v2_plan_with_a_coherent_v2_manifest_is_v2(tmp_path):
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v2_plan(), manifest=v2_manifest())) == "v2"


def test_the_result_is_only_ever_the_string_v1_or_v2_and_str_paths_work(tmp_path):
    for plan, expected in ((v1_plan(), "v1"), (v2_plan(), "v2")):
        directory = campaign(tmp_path, plan=plan, label=expected)
        for argument in (directory, str(directory)):
            result = d6.classify_gate_v_campaign_dir(argument)
            assert type(result) is str and result == expected


def test_extra_unknown_keys_do_not_change_the_classification(tmp_path):
    """D6 ne lit que les clés de discrimination : tout le reste est hors sujet (aucune validation scientifique)."""
    assert d6.classify_gate_v_campaign_dir(
        campaign(tmp_path, plan=v1_plan(whatever=[1, 2], nested={"a": None}), label="a")) == "v1"
    assert d6.classify_gate_v_campaign_dir(
        campaign(tmp_path, plan=v2_plan(split_plan_id=None, walk_forward_specification="bogus"), label="b")) == "v2"


# ============================================================================================
# Tranche 2 — matrice NÉGATIVE du plan (étapes 1 à 4 de §21.9) : tout état refusé lève l'erreur de discrimination
# ============================================================================================


def test_an_invalid_campaign_dir_argument_is_a_discrimination_error(tmp_path):
    for bad in (None, "", "   ", 5, 5.0, b"bytes", ["x"], {"a": 1}, True):
        with pytest.raises(Error, match="campaign_dir"):
            d6.classify_gate_v_campaign_dir(bad)
    with pytest.raises(Error, match="plan.json"):  # dossier inexistant : le plan est introuvable
        d6.classify_gate_v_campaign_dir(tmp_path / "does_not_exist")


@pytest.mark.parametrize("content", [
    pytest.param(None, id="absent"),
    pytest.param("", id="empty_file"),
    pytest.param("   \n", id="blank_file"),
    pytest.param('{"campaign_plan_semantics_version": "gate_v_campaign_plan_v2", "campaign_id": "gate_v_v2_',
                 id="truncated"),
    pytest.param("{", id="open_brace"),
    pytest.param("not json at all", id="garbage"),
    pytest.param("42", id="json_scalar_number"),
    pytest.param('"plan"', id="json_scalar_string"),
    pytest.param("true", id="json_scalar_bool"),
    pytest.param("[]", id="json_empty_list"),
    pytest.param(json.dumps([v2_plan()]), id="json_list_of_plans"),
    pytest.param("null", id="json_null"),
    pytest.param(b"\xff\xfe\x00bad-utf8", id="not_utf8"),
    pytest.param("﻿" + json.dumps(v1_plan()), id="utf8_bom"),
])
def test_an_absent_unreadable_or_non_object_plan_is_refused(tmp_path, content):
    directory = campaign(tmp_path, plan=content, name=V1_ID)
    with pytest.raises(Error, match="plan.json"):
        d6.classify_gate_v_campaign_dir(directory)


def test_a_directory_in_place_of_plan_json_is_refused(tmp_path):
    directory = tmp_path / V1_ID
    (directory / "plan.json").mkdir(parents=True)
    with pytest.raises(Error, match="plan.json"):
        d6.classify_gate_v_campaign_dir(directory)


def test_a_pathologically_nested_json_is_a_discrimination_error_never_a_raw_recursion_error(tmp_path):
    """`RecursionError` (profondeur JSON) n'est pas une `ValueError` : sans normalisation, un `plan.json` ou un
    `manifest.json` illisible par sa profondeur ferait échapper une erreur non classée à l'appelant (§21.9 : « illisible »
    = erreur de discrimination)."""
    nested = "[" * 200_000 + "]" * 200_000
    plan = '{"campaign_id": "%s", "x": %s}' % (V1_ID, nested)
    with pytest.raises(Error, match="plan.json"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan, name=V1_ID, label="plan"))
    manifest = '{"campaign_id": "%s", "x": %s}' % (V1_ID, nested)
    with pytest.raises(Error, match="manifest.json"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan(), manifest=manifest, label="manifest"))


@pytest.mark.parametrize("version", [
    None, "", " ", "v1", "V2", "gate_v_campaign_plan_v1", "gate_v_campaign_plan_v3", "gate_v_campaign_plan_v2 ",
    " gate_v_campaign_plan_v2", "GATE_V_CAMPAIGN_PLAN_V2", "gate_v_campaign_manifest_v2", 2, 0, 1.5, True, False,
    {}, [], ["gate_v_campaign_plan_v2"], {"v": PLAN_V2},
])
def test_a_present_but_unknown_plan_semantics_is_refused_and_never_read_as_v1(tmp_path, version):
    """Clé ABSENTE = V1 ; clé PRÉSENTE avec n'importe quelle autre valeur que la constante exacte = erreur fermée
    (`None` compris) : jamais reclassée V1."""
    record = {"campaign_plan_semantics_version": version, "campaign_id": V1_ID}
    with pytest.raises(Error, match="campaign_plan_semantics_version"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=record, name=V1_ID))
    record = {"campaign_plan_semantics_version": version, "campaign_id": V2_ID}
    with pytest.raises(Error, match="campaign_plan_semantics_version"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=record, name=V2_ID, label="v2"))


def test_an_absent_key_is_not_the_same_as_a_key_present_with_none(tmp_path):
    absent = campaign(tmp_path, plan={"campaign_id": V1_ID}, label="absent")
    present_none = campaign(tmp_path, plan={"campaign_plan_semantics_version": None, "campaign_id": V1_ID},
                            label="none")
    assert d6.classify_gate_v_campaign_dir(absent) == "v1"
    with pytest.raises(Error):
        d6.classify_gate_v_campaign_dir(present_none)


@pytest.mark.parametrize("record", [
    pytest.param({}, id="v1_no_campaign_id"),
    pytest.param({"campaign_plan_semantics_version": PLAN_V2}, id="v2_no_campaign_id"),
    pytest.param({"campaign_id": None}, id="v1_campaign_id_none"),
    pytest.param({"campaign_id": 5}, id="v1_campaign_id_number"),
    pytest.param({"campaign_id": True}, id="v1_campaign_id_bool"),
    pytest.param({"campaign_id": [V1_ID]}, id="v1_campaign_id_list"),
    pytest.param({"campaign_id": {"id": V1_ID}}, id="v1_campaign_id_object"),
    pytest.param({"campaign_plan_semantics_version": PLAN_V2, "campaign_id": None}, id="v2_campaign_id_none"),
    pytest.param({"campaign_plan_semantics_version": PLAN_V2, "campaign_id": [V2_ID]}, id="v2_campaign_id_list"),
])
def test_a_plan_without_a_string_campaign_id_is_refused(tmp_path, record):
    with pytest.raises(Error, match="campaign_id du plan"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=record, name=V1_ID))


_BAD_V1_IDS = {
    "v2_id_under_a_v1_plan": V2_ID,
    "uppercase_hex": "gate_v_" + "AB" * 32,
    "mixed_case_hex": "gate_v_" + "aB" * 32,
    "63_hex": "gate_v_" + "ab" * 31 + "a",
    "65_hex": "gate_v_" + "ab" * 32 + "a",
    "empty_hash": "gate_v_",
    "wrong_prefix": "gate_" + "ab" * 32,
    "prefix_with_dash": "gate-v-" + "ab" * 32,
    "non_hex_char": "gate_v_" + "ab" * 31 + "zz",
    "leading_junk": "x" + V1_ID,
    "trailing_junk": V1_ID + "x",
    "trailing_newline": V1_ID + "\n",
    "leading_space": " " + V1_ID,
    "trailing_space": V1_ID + " ",
    "v2_marker_inside": "gate_v_v2_" + "ab" * 32,
    "empty": "",
}
_BAD_V2_IDS = {
    "v1_id_under_a_v2_plan": V1_ID,
    "uppercase_hex": "gate_v_v2_" + "CD" * 32,
    "63_hex": "gate_v_v2_" + "cd" * 31 + "c",
    "65_hex": "gate_v_v2_" + "cd" * 32 + "c",
    "missing_v2_marker": "gate_v_" + "cd" * 32,
    "double_marker": "gate_v_v2_v2_" + "cd" * 32,
    "empty_hash": "gate_v_v2_",
    "non_hex_char": "gate_v_v2_" + "cd" * 31 + "zz",
    "leading_junk": "x" + V2_ID,
    "trailing_junk": V2_ID + "x",
    "trailing_newline": V2_ID + "\n",
    "leading_space": " " + V2_ID,
    "empty": "",
}


@pytest.mark.parametrize("campaign_id", list(_BAD_V1_IDS.values()), ids=list(_BAD_V1_IDS))
def test_a_v1_plan_accepts_only_the_exact_v1_identifier_form(tmp_path, campaign_id):
    directory = campaign(tmp_path, plan=v1_plan(campaign_id), name="whatever_name")
    with pytest.raises(Error, match="campaign_id du plan"):
        d6.classify_gate_v_campaign_dir(directory)


@pytest.mark.parametrize("campaign_id", list(_BAD_V2_IDS.values()), ids=list(_BAD_V2_IDS))
def test_a_v2_plan_accepts_only_the_exact_v2_identifier_form(tmp_path, campaign_id):
    directory = campaign(tmp_path, plan=v2_plan(campaign_id), name="whatever_name")
    with pytest.raises(Error, match="campaign_id du plan"):
        d6.classify_gate_v_campaign_dir(directory)


def test_the_v1_and_v2_identifier_spaces_are_disjoint_in_both_directions(tmp_path):
    """`gate_v_<64 hex>` et `gate_v_v2_<64 hex>` ne se recoupent jamais : le segment `v2_` n'est pas hexadécimal."""
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan(V1_ID), label="v1")) == "v1"
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v2_plan(V2_ID), label="v2")) == "v2"
    with pytest.raises(Error):  # id V1 présenté sous un plan V2
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v2_plan(V1_ID), label="x2"))
    with pytest.raises(Error):  # id V2 présenté sous un plan V1
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan(V2_ID), label="x1"))


def test_the_directory_name_must_equal_the_plan_campaign_id(tmp_path):
    for plan, wrong in ((v1_plan(), "not_the_campaign_id"), (v2_plan(), "gate_v_v2_" + "ee" * 32),
                        (v1_plan(), V1_ID.upper()), (v2_plan(), V2_ID + "_copy")):
        with pytest.raises(Error, match="nom du dossier"):
            d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan, name=wrong, label=wrong[-8:]))


def test_the_directory_name_is_never_the_discriminant(tmp_path):
    """Un dossier nommé `gate_v_v2_…` contenant un vrai plan V1 N'EST PAS classé V2 par son nom : le contenu décide
    (v1), puis le nom incohérent avec le `campaign_id` V1 est refusé. Symétriquement pour un nom V1 et un plan V2."""
    v1_in_v2_named_dir = campaign(tmp_path, plan=v1_plan(), name=V2_ID, label="a")
    v2_in_v1_named_dir = campaign(tmp_path, plan=v2_plan(), name=V1_ID, label="b")
    for directory in (v1_in_v2_named_dir, v2_in_v1_named_dir):
        with pytest.raises(Error, match="nom du dossier"):
            d6.classify_gate_v_campaign_dir(directory)
    # Et un nom qui « ressemble » à V2 ne rend jamais V2 un plan sans version : même verdict que sans le nom.
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v1_plan(), name=V1_ID, label="c")) == "v1"


# ============================================================================================
# Tranche 3 — manifest : ABSENT (normal, plan persisté avant lui) vs PRÉSENT mais inutilisable (étapes 4 à 7 de §21.9)
# ============================================================================================

_COHERENT = {"v1": (v1_plan, v1_manifest), "v2": (v2_plan, v2_manifest)}


@pytest.mark.parametrize("kind", ["v1", "v2"])
def test_a_manifest_that_is_really_absent_returns_the_plan_kind(tmp_path, kind):
    """Le Plan peut être persisté avant la création du Manifest : l'absence est un état NORMAL, pas une erreur."""
    plan = _COHERENT[kind][0]()
    directory = campaign(tmp_path, plan=plan, manifest=None)
    assert not (directory / "manifest.json").exists()
    assert d6.classify_gate_v_campaign_dir(directory) == kind


@pytest.mark.parametrize("kind", ["v1", "v2"])
@pytest.mark.parametrize("content", [
    pytest.param("", id="empty_file"),
    pytest.param("   \n", id="blank_file"),
    pytest.param('{"campaign_id": "gate_v_', id="truncated"),
    pytest.param("{", id="open_brace"),
    pytest.param("not json", id="garbage"),
    pytest.param("42", id="json_scalar_number"),
    pytest.param('"manifest"', id="json_scalar_string"),
    pytest.param("[]", id="json_empty_list"),
    pytest.param("[{}]", id="json_list_of_objects"),
    pytest.param("null", id="json_null"),
    pytest.param(b"\xff\xfe\x00bad-utf8", id="not_utf8"),
    pytest.param("﻿{}", id="utf8_bom"),
])
def test_a_present_but_unusable_manifest_is_refused_never_treated_as_absent(tmp_path, kind, content):
    directory = campaign(tmp_path, plan=_COHERENT[kind][0](), manifest=content)
    with pytest.raises(Error, match="manifest.json"):
        d6.classify_gate_v_campaign_dir(directory)


@pytest.mark.parametrize("kind", ["v1", "v2"])
def test_a_directory_in_place_of_manifest_json_is_refused_not_absent(tmp_path, kind):
    directory = campaign(tmp_path, plan=_COHERENT[kind][0]())
    (directory / "manifest.json").mkdir()
    with pytest.raises(Error, match="manifest.json"):
        d6.classify_gate_v_campaign_dir(directory)


@pytest.mark.parametrize("version", [
    None, "", " ", "v1", "V2", "gate_v_campaign_manifest_v1", "gate_v_campaign_manifest_v3",
    "gate_v_campaign_manifest_v2 ", " gate_v_campaign_manifest_v2", "GATE_V_CAMPAIGN_MANIFEST_V2",
    "gate_v_campaign_plan_v2", 2, 0, 1.5, True, False, {}, [], ["gate_v_campaign_manifest_v2"],
])
@pytest.mark.parametrize("kind", ["v1", "v2"])
def test_a_present_but_unknown_manifest_semantics_is_refused_under_either_plan(tmp_path, kind, version):
    """Même règle que pour le plan : clé absente = v1 ; clé présente avec une valeur autre que la constante exacte
    (`None` compris) = erreur fermée, jamais reclassée v1 ni « réparée »."""
    plan, _ = _COHERENT[kind]
    campaign_id = V1_ID if kind == "v1" else V2_ID
    record = {"manifest_semantics_version": version, "campaign_id": campaign_id}
    with pytest.raises(Error, match="manifest_semantics_version"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan(), manifest=record))


def test_a_manifest_key_present_with_none_is_not_the_same_as_an_absent_key(tmp_path):
    assert d6.classify_gate_v_campaign_dir(
        campaign(tmp_path, plan=v1_plan(), manifest={"campaign_id": V1_ID}, label="absent")) == "v1"
    with pytest.raises(Error):
        d6.classify_gate_v_campaign_dir(campaign(
            tmp_path, plan=v1_plan(), manifest={"manifest_semantics_version": None, "campaign_id": V1_ID}, label="none"))


def test_a_hybrid_v1_plan_with_a_v2_manifest_is_refused(tmp_path):
    with pytest.raises(Error, match="hybride"):
        d6.classify_gate_v_campaign_dir(
            campaign(tmp_path, plan=v1_plan(), manifest=v2_manifest(campaign_id=V1_ID)))


def test_a_hybrid_v2_plan_with_a_v1_manifest_is_refused(tmp_path):
    with pytest.raises(Error, match="hybride"):
        d6.classify_gate_v_campaign_dir(
            campaign(tmp_path, plan=v2_plan(), manifest=v1_manifest(campaign_id=V2_ID)))


def test_a_hybrid_state_is_never_repaired_in_favour_of_the_plan_or_the_manifest(tmp_path):
    """Aucune préférence : ni « le plan fait foi » (v1/v2), ni « le manifest fait foi »."""
    for plan, manifest, plan_id in ((v1_plan(), v2_manifest(V1_ID), V1_ID), (v2_plan(), v1_manifest(V2_ID), V2_ID)):
        with pytest.raises(Error) as raised:
            d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan, manifest=manifest, label=plan_id[:12]))
        assert "hybride" in str(raised.value)


@pytest.mark.parametrize("kind", ["v1", "v2"])
@pytest.mark.parametrize("campaign_id", [
    pytest.param(None, id="none"), pytest.param(5, id="number"), pytest.param(True, id="bool"),
    pytest.param(["x"], id="list"), pytest.param({"id": "x"}, id="object"), pytest.param("", id="empty"),
    pytest.param("other", id="other_string"), pytest.param("__MISSING__", id="absent"),
])
def test_a_manifest_campaign_id_that_is_absent_not_a_string_or_not_equal_is_refused(tmp_path, kind, campaign_id):
    plan, manifest = _COHERENT[kind]
    record = manifest()
    if campaign_id == "__MISSING__":
        del record["campaign_id"]
    else:
        record["campaign_id"] = campaign_id
    with pytest.raises(Error, match="campaign_id du manifest"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan(), manifest=record))


@pytest.mark.parametrize("kind", ["v1", "v2"])
def test_a_well_formed_but_different_manifest_campaign_id_is_refused(tmp_path, kind):
    """Une AUTRE campagne valide ne passe pas : seule l'égalité exacte avec l'identifiant du plan est acceptée.
    D6 ne recalcule jamais le `campaign_id` (elle ne connaît pas le protocole scientifique)."""
    plan, manifest = _COHERENT[kind]
    other = ("gate_v_" if kind == "v1" else "gate_v_v2_") + "ef" * 32
    with pytest.raises(Error, match="campaign_id du manifest"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan(), manifest=manifest(campaign_id=other)))
    upper = (V1_ID if kind == "v1" else V2_ID).replace("ab", "AB").replace("cd", "CD")
    with pytest.raises(Error, match="campaign_id du manifest"):
        d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan(), manifest=manifest(campaign_id=upper),
                                                 label="upper"))


# ============================================================================================
# Tranche 4 — AUCUN repli : une version explicitement déclarée mais malformée reste une erreur, jamais V1
# ============================================================================================


def test_a_declared_but_malformed_v2_never_falls_back_to_v1(tmp_path):
    malformed_v2_plans = (
        v2_plan(campaign_id=V1_ID),  # id d'un autre espace
        v2_plan(campaign_id=None),
        {"campaign_plan_semantics_version": PLAN_V2},  # sans identifiant
    )
    for index, plan in enumerate(malformed_v2_plans):
        with pytest.raises(Error):
            d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan, name=V1_ID, label=f"p{index}"))
    for index, manifest in enumerate(("{", "[]", v1_manifest(V2_ID), v2_manifest("gate_v_v2_other"))):
        with pytest.raises(Error):
            d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=v2_plan(), manifest=manifest, label=f"m{index}"))


def test_a_v2_plan_is_never_reduced_to_v1_even_when_its_other_content_looks_like_a_v1_plan(tmp_path):
    """Plan V2 déclaré dont tout le reste ressemble à un plan V1 : toujours v2 (ou une erreur), jamais v1."""
    plan = v2_plan(research_run_id="research_synthetic", split_plan_id="s", **{"strategy_name": "S"})
    assert d6.classify_gate_v_campaign_dir(campaign(tmp_path, plan=plan)) == "v2"


# ============================================================================================
# Tranche 5 — fichiers lus, pas de balayage, fichiers parasites, lecture seule DYNAMIQUE
# ============================================================================================

_PARASITES = {
    "technical_failure.json": b"",  # sentinelle d'échec : jamais lue, ne change rien
    "manifest.update.lock": b"held by another writer",
    "random.tmp": b"\x00\x01",
    "final_holdout_access_claim.json": b"{}",  # un faux « Claim » n'a aucun effet sur la version
    "assessment.json": b"not json",
}


def _add_parasites(directory):
    for name, content in _PARASITES.items():
        (directory / name).write_bytes(content)
    (directory / "validations" / "anything").mkdir(parents=True)
    (directory / "validations" / "anything" / "validation_run.json").write_text("garbage", encoding="utf-8")
    (directory / "assessments").mkdir()


def _snapshot(directory):
    return {
        path.relative_to(directory).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(directory.rglob("*")) if path.is_file()
    }


_EVERY_STATE = {
    "v1_plan_only": lambda tp, lb: campaign(tp, plan=v1_plan(), label=lb),
    "v2_plan_only": lambda tp, lb: campaign(tp, plan=v2_plan(), label=lb),
    "v1_with_manifest": lambda tp, lb: campaign(tp, plan=v1_plan(), manifest=v1_manifest(), label=lb),
    "v2_with_manifest": lambda tp, lb: campaign(tp, plan=v2_plan(), manifest=v2_manifest(), label=lb),
}


@pytest.mark.parametrize("state", list(_EVERY_STATE))
def test_parasite_files_and_folders_never_change_nor_are_read_by_the_classification(tmp_path, monkeypatch, state):
    import io

    expected = d6.classify_gate_v_campaign_dir(_EVERY_STATE[state](tmp_path, "clean"))
    dirty = _EVERY_STATE[state](tmp_path, "dirty")
    _add_parasites(dirty)
    opened = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(file)))
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(io, "open", spy)
    assert d6.classify_gate_v_campaign_dir(dirty) == expected
    assert set(opened) <= {"plan.json", "manifest.json"}, opened  # aucun parasite n'est ouvert


@pytest.mark.parametrize("state, expected_opens", [
    ("v1_plan_only", ["plan.json", "manifest.json"]), ("v2_plan_only", ["plan.json", "manifest.json"]),
    ("v1_with_manifest", ["plan.json", "manifest.json"]), ("v2_with_manifest", ["plan.json", "manifest.json"]),
])
def test_at_most_plan_json_then_manifest_json_are_opened_in_that_order(tmp_path, monkeypatch, state, expected_opens):
    """Succès : exactement `plan.json` puis `manifest.json` (la tentative sur un manifest absent compte comme lecture)."""
    import io

    directory = _EVERY_STATE[state](tmp_path, "c")
    opened = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(file)))
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(io, "open", spy)
    d6.classify_gate_v_campaign_dir(directory)
    assert opened == expected_opens


def test_a_refusal_before_the_manifest_step_never_opens_the_manifest(tmp_path, monkeypatch):
    """Plan inutilisable, version inconnue, id invalide ou nom incohérent : `manifest.json` n'est même pas ouvert."""
    import io

    cases = [
        campaign(tmp_path, plan="{", name=V1_ID, manifest=v1_manifest(), label="a"),
        campaign(tmp_path, plan={"campaign_plan_semantics_version": "x", "campaign_id": V1_ID}, manifest=v1_manifest(),
                 label="b"),
        campaign(tmp_path, plan=v2_plan(V1_ID), manifest=v2_manifest(), name=V1_ID, label="c"),
        campaign(tmp_path, plan=v1_plan(), manifest=v1_manifest(), name="wrong_name", label="d"),
    ]
    opened = []
    real_open = io.open

    def spy(file, *args, **kwargs):
        opened.append(os.path.basename(os.fspath(file)))
        return real_open(file, *args, **kwargs)
    monkeypatch.setattr(io, "open", spy)
    for directory in cases:
        with pytest.raises(Error):
            d6.classify_gate_v_campaign_dir(directory)
    assert opened == ["plan.json"] * len(cases)


@pytest.mark.parametrize("state", list(_EVERY_STATE))
def test_the_classification_never_scans_the_directory(tmp_path, monkeypatch, state):
    from pathlib import Path

    directory = _EVERY_STATE[state](tmp_path, "c")
    _add_parasites(directory)
    expected = {"v1_plan_only": "v1", "v1_with_manifest": "v1", "v2_plan_only": "v2", "v2_with_manifest": "v2"}[state]

    def forbidden(*args, **kwargs):
        raise AssertionError("aucun inventaire de dossier")
    for owner, name in ((os, "scandir"), (os, "listdir"), (os, "walk"), (os, "fwalk"), (Path, "iterdir"),
                        (Path, "glob"), (Path, "rglob"), (Path, "walk")):
        if hasattr(owner, name):
            monkeypatch.setattr(owner, name, forbidden)
    assert d6.classify_gate_v_campaign_dir(directory) == expected


@pytest.mark.parametrize("state", list(_EVERY_STATE))
def test_the_classification_is_read_only_dynamically_on_success_and_on_failure(tmp_path, monkeypatch, state):
    """Mêmes fichiers, mêmes octets, mêmes mtimes ; sous des appels système d'ÉCRITURE interdits."""
    import io
    from pathlib import Path

    good = _EVERY_STATE[state](tmp_path, "good")
    _add_parasites(good)
    bad = campaign(tmp_path, plan=v1_plan(), manifest="{", label="bad")  # un échec représentatif
    before = {directory: _snapshot(directory) for directory in (good, bad)}
    real_io_open, real_os_open = io.open, os.open

    def guarded_io_open(file, mode="r", *args, **kwargs):
        assert not set(mode) & set("wax+"), f"ouverture en écriture interdite : {file!r} {mode!r}"
        return real_io_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        assert not flags & (os.O_CREAT | os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_TRUNC | os.O_EXCL)
        return real_os_open(path, flags, *args, **kwargs)

    def forbidden(*args, **kwargs):
        raise AssertionError("opération d'écriture interdite en lecture seule")
    monkeypatch.setattr(io, "open", guarded_io_open)
    monkeypatch.setattr("builtins.open", guarded_io_open)
    monkeypatch.setattr(os, "open", guarded_os_open)
    for name in ("replace", "rename", "unlink", "remove", "mkdir", "makedirs", "rmdir", "write", "utime", "chmod",
                 "truncate"):
        monkeypatch.setattr(os, name, forbidden)
    for name in ("mkdir", "unlink", "rename", "replace", "write_text", "write_bytes", "touch", "rmdir", "symlink_to"):
        monkeypatch.setattr(Path, name, forbidden)
    d6.classify_gate_v_campaign_dir(good)
    with pytest.raises(Error):
        d6.classify_gate_v_campaign_dir(bad)
    monkeypatch.undo()
    assert {directory: _snapshot(directory) for directory in (good, bad)} == before


# ============================================================================================
# Tranche 6 — architecture (AST) : stdlib seule, aucun module scientifique, aucun chargeur, aucune écriture,
#   aucun balayage, aucun Claim / FINAL_HOLDOUT, aucune façade d'exécution, module MINUSCULE (YAGNI)
# ============================================================================================

_MODULE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gate_v_campaign_dispatch.py")


def _tree():
    import ast

    with open(_MODULE_PATH, encoding="utf-8") as handle:
        return ast.parse(handle.read())


def _code_identifiers(tree):
    """Identifiants de CODE (noms, attributs, définitions, imports) — jamais les docstrings ni les chaînes."""
    import ast

    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.alias):
            names.add(node.name.split(".")[0])
            names.add((node.asname or node.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def test_the_module_imports_only_the_standard_library_and_no_scientific_module():
    import ast

    imported = set()
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert imported == {"__future__", "json", "re", "pathlib"}
    forbidden = {
        "gate_v_campaign", "gate_v_campaign_plan_v2", "gate_v_campaign_manifest_v2", "gate_v_evidence_completeness_v2",
        "validation_run", "walk_forward", "monte_carlo", "parameter_stability", "validation_oos", "engine", "optimizer",
        "gate_v_preregistration", "gate_v_validation_policy", "atomic_json_store", "research_run", "dataset_split",
        "subprocess", "os", "shutil", "tempfile", "glob", "hashlib", "time", "datetime", "uuid", "random",
    }
    assert not imported & forbidden


def test_importing_the_module_loads_no_scientific_module_even_transitively():
    import subprocess

    code = (
        "import sys, gate_v_campaign_dispatch;"
        "banned = {'gate_v_campaign', 'gate_v_campaign_plan_v2', 'gate_v_campaign_manifest_v2',"
        " 'gate_v_evidence_completeness_v2', 'validation_run', 'walk_forward', 'monte_carlo', 'parameter_stability',"
        " 'validation_oos', 'engine', 'optimizer', 'gate_v_preregistration', 'gate_v_validation_policy',"
        " 'atomic_json_store'};"
        "assert not banned & set(sys.modules), sorted(banned & set(sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=os.path.dirname(_MODULE_PATH), capture_output=True,
                            text=True)
    assert result.returncode == 0, result.stderr


def test_the_module_calls_no_strict_loader_no_write_no_scan_no_claim_and_no_execution_facade():
    identifiers = _code_identifiers(_tree())
    forbidden = {
        # chargeurs stricts V1/V2 : D6 ne valide jamais, elle classe
        "load_gate_v_campaign_plan", "load_gate_v_campaign_manifest", "load_gate_v_campaign_plan_v2",
        "load_gate_v_campaign_manifest_v2", "gate_v_campaign_manifest_v2_from_record", "load_validation_run",
        "load_json_tolerant", "load_tolerant",
        # écritures et verrous
        "write_text", "write_bytes", "open", "unlink", "rename", "replace", "mkdir", "makedirs", "rmdir", "touch",
        "chmod", "utime", "symlink_to", "save_exclusive", "save_atomic", "save_atomic_overwrite", "dump", "fsync",
        # balayage de dossier et tests d'existence préalables (TOCTOU) : deux chemins canoniques lus directement
        "iterdir", "glob", "rglob", "walk", "scandir", "listdir", "exists", "is_file", "is_dir", "stat", "lstat",
        # nom du dossier comme discriminant
        "startswith", "endswith",
        # Claim / FINAL_HOLDOUT / évaluation / exécution
        "FinalHoldoutAccessClaim", "HoldoutAccessEvent", "run_oos_validation", "run_gate_v_final_holdout_validation",
        "ValidationAssessment", "GateVPolicyAssessment", "execute_gate_v_campaign", "assert_gate_v_pre_holdout_evidence_complete",
        "evaluate_pre_holdout_evidence_v2", "technical_failure", "validations",
    }
    assert not identifiers & forbidden, sorted(identifiers & forbidden)
    # Seul le contenu de deux fichiers est lu, et seulement par `read_text` (jamais d'ouverture en écriture).
    assert {"read_text", "loads"} <= identifiers


def test_no_execution_facade_registry_factory_or_common_protocol_exists():
    for name in ("execute_gate_v_campaign_any", "dispatch_gate_v_campaign", "load_any_gate_v_campaign", "run_campaign",
                 "execute_v1_or_v2", "register_version", "resolve_version", "GateVVersionResolver", "CampaignFactory",
                 "CampaignProtocol", "VERSION_REGISTRY"):
        assert not hasattr(d6, name), name
    import ast

    classes = [node.name for node in ast.walk(_tree()) if isinstance(node, ast.ClassDef)]
    assert classes == ["GateVCampaignDiscriminationError"]  # une seule classe : l'erreur publique


def test_the_module_stays_tiny():
    """Raison d'être (test de suppression) : sans lui, chaque appelant réimplémenterait l'algorithme §21.9. Il ne doit
    donc rester qu'une fonction focalisée — pas un framework."""
    with open(_MODULE_PATH, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    assert len(lines) <= 130, len(lines)
    import ast

    functions = [node.name for node in _tree().body if isinstance(node, ast.FunctionDef)]
    assert functions == ["_read_json_object", "classify_gate_v_campaign_dir"]


# ============================================================================================
# Tranche 7 — non-dérive : la duplication VOLONTAIRE des littéraux est comparée aux constantes publiques V2 et à de
#   VRAIS artefacts produits par les modules V1/V2 (dépendances de TEST seulement, jamais d'exécution)
# ============================================================================================


def test_the_duplicated_literals_equal_the_public_v2_constants():
    import re

    import gate_v_campaign_manifest_v2 as manifest_v2
    import gate_v_campaign_plan_v2 as plan_v2

    assert d6._PLAN_V2_SEMANTICS_VERSION == plan_v2.GATE_V_CAMPAIGN_PLAN_V2_SEMANTICS_VERSION
    assert d6._MANIFEST_V2_SEMANTICS_VERSION == manifest_v2.GATE_V_CAMPAIGN_MANIFEST_V2_SEMANTICS_VERSION
    assert d6._CAMPAIGN_ID_FORMS["v2"].pattern == re.escape(plan_v2.GATE_V_CAMPAIGN_ID_V2_PREFIX) + "[0-9a-f]{64}"
    assert d6._PLAN_VERSION_KEY in {"campaign_plan_semantics_version"}
    assert d6._MANIFEST_VERSION_KEY in {field.name for field in __import__("dataclasses").fields(
        manifest_v2.GateVCampaignManifestV2)}


@pytest.fixture(scope="module")
def real_campaigns(tmp_path_factory):
    """Vrais plans et manifests V1 et V2 produits par les modules existants (jamais modifiés), persistés sur disque."""
    import dataclasses

    import gate_v_campaign
    import gate_v_campaign_manifest_v2 as manifest_v2
    import gate_v_campaign_plan_v2 as plan_v2
    from dataset_split import save_dataset_split_plan
    from tests import test_gate_v_campaign_manifest_v2 as source

    root = tmp_path_factory.mktemp("d6_real")
    split = source._split_plan()
    split_path = root / "split.json"
    save_dataset_split_plan(split_path, split)
    plan = source._build_plan_v2(root, split, budget_per_fold=20)
    v2_dir = plan_v2.save_gate_v_campaign_plan_v2(root / "v2", plan).parent
    manifest_v2.create_gate_v_campaign_manifest_v2(plan, v2_dir)
    v1_plan_object = gate_v_campaign.build_gate_v_campaign_plan(
        research_run_id=source._RESEARCH_RUN_ID, dataset_snapshot_id=source._SNAPSHOT_ID,
        split_plan_id=source._SPLIT_PLAN_ID, split_plan_path=split_path, strategy_name=source._STRATEGY,
        geometry="rolling", train_period="P24M", test_period="P6M", step_period="P6M", readiness_spec=None,
        master_seed=None, budget_per_fold=20, **source._PROTOCOL,
    )
    v1_dir = gate_v_campaign.save_gate_v_campaign_plan(root / "v1", v1_plan_object).parent
    v1_manifest_record = dataclasses.asdict(gate_v_campaign.build_gate_v_campaign_manifest(v1_plan_object))
    return {"v1": v1_dir, "v2": v2_dir, "v1_manifest": v1_manifest_record, "v2_plan": plan,
            "v1_plan": v1_plan_object}


def test_real_v2_artifacts_are_classified_v2_with_and_without_the_manifest(real_campaigns):
    directory = real_campaigns["v2"]
    assert (directory / "manifest.json").is_file()
    assert d6.classify_gate_v_campaign_dir(directory) == "v2"
    manifest_bytes = (directory / "manifest.json").read_bytes()
    (directory / "manifest.json").unlink()
    try:
        assert d6.classify_gate_v_campaign_dir(directory) == "v2"
    finally:
        (directory / "manifest.json").write_bytes(manifest_bytes)
    assert d6.classify_gate_v_campaign_dir(directory) == "v2"


def test_real_v1_artifacts_are_classified_v1_with_and_without_the_manifest(real_campaigns):
    directory = real_campaigns["v1"]
    assert directory.name == real_campaigns["v1_plan"].campaign_id and directory.name.startswith("gate_v_")
    assert not directory.name.startswith("gate_v_v2_")
    assert d6.classify_gate_v_campaign_dir(directory) == "v1"
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(real_campaigns["v1_manifest"]), encoding="utf-8")
    try:
        assert "manifest_semantics_version" not in real_campaigns["v1_manifest"]
        assert d6.classify_gate_v_campaign_dir(directory) == "v1"
    finally:
        manifest.unlink()


def test_a_real_v1_manifest_in_a_real_v2_campaign_and_the_reverse_are_hybrid_errors(real_campaigns, tmp_path):
    import shutil

    v2_dir = tmp_path / "v2" / real_campaigns["v2"].name
    shutil.copytree(real_campaigns["v2"], v2_dir)
    record = dict(real_campaigns["v1_manifest"], campaign_id=real_campaigns["v2_plan"].campaign_id)
    (v2_dir / "manifest.json").write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(Error, match="hybride"):
        d6.classify_gate_v_campaign_dir(v2_dir)
    v1_dir = tmp_path / "v1" / real_campaigns["v1"].name
    shutil.copytree(real_campaigns["v1"], v1_dir)
    real_v2_manifest = json.loads((real_campaigns["v2"] / "manifest.json").read_text(encoding="utf-8"))
    (v1_dir / "manifest.json").write_text(
        json.dumps(dict(real_v2_manifest, campaign_id=real_campaigns["v1_plan"].campaign_id)), encoding="utf-8")
    with pytest.raises(Error, match="hybride"):
        d6.classify_gate_v_campaign_dir(v1_dir)


def test_real_campaign_identifiers_have_exactly_the_documented_disjoint_forms(real_campaigns):
    v1_id, v2_id = real_campaigns["v1_plan"].campaign_id, real_campaigns["v2_plan"].campaign_id
    assert d6._CAMPAIGN_ID_FORMS["v1"].fullmatch(v1_id) and not d6._CAMPAIGN_ID_FORMS["v2"].fullmatch(v1_id)
    assert d6._CAMPAIGN_ID_FORMS["v2"].fullmatch(v2_id) and not d6._CAMPAIGN_ID_FORMS["v1"].fullmatch(v2_id)
