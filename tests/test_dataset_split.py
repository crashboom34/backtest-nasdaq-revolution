"""
tests/test_dataset_split.py — AF-R-03 : DatasetSplitPlan / HoldoutAccessEvent, fondations
(Track R, après AF-R-01/AF-R-02).

DatasetSplitPlan = partition logique déclarative d'une version de dataset déjà identifiée
(dataset_snapshot_id, produit par AF-DATA) en zones TRAIN/VALIDATION/DISCOVERY_OOS/FINAL_HOLDOUT —
jamais une nouvelle DatasetVersion, jamais une copie/modification du CSV source (voir
docs/architecture/DOMAIN_MODEL.md §12, note "Résolution AF-R-03").

**Cardinalité (revue corrective, 2026-08-15)** : `DatasetSplitPlan` est identifié par son PROPRE
`split_plan_id` (pas par `dataset_snapshot_id`) — plusieurs plans peuvent légitimement référencer
le même snapshot (deux `ResearchRun` choisissant des découpages différents du même CSV source).

HoldoutAccessEvent = journal d'audit append-only, observable, PAS un contrôle d'accès technique —
rend une consultation du FINAL_HOLDOUT visible (research_run_id, split_plan_id, motif, horodatage),
sans l'empêcher. Aucune fonction ne doit affirmer qu'un holdout est "untouched" : seule
has_holdout_access_events() (constat factuel de CE répertoire d'audit) est fournie.

Aucune base de données, aucune UI, aucun câblage optimizer_process.py/job_store.py : fondations
pures, persistance fichier, testées avec tmp_path/dates synthétiques uniquement.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dataset_split import (
    DatasetSplitPlan,
    HoldoutAccessEvent,
    SplitBoundary,
    build_dataset_split_plan,
    build_holdout_access_event,
    build_split_boundary,
    has_holdout_access_events,
    list_holdout_access_events,
    load_dataset_split_plan,
    load_holdout_access_event,
    save_dataset_split_plan,
    save_holdout_access_event,
    split_plan_slug,
)

_SNAPSHOT_ID = "local_csv:sha256:" + "ab" * 32


def _boundary(start, end):
    return build_split_boundary(start=start, end=end)


def _plan(split_plan_id="plan_a", dataset_snapshot_id=_SNAPSHOT_ID, **kwargs):
    kwargs.setdefault("train", _boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"))
    kwargs.setdefault(
        "final_holdout", _boundary("2024-09-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00")
    )
    return build_dataset_split_plan(
        split_plan_id=split_plan_id, dataset_snapshot_id=dataset_snapshot_id, **kwargs
    )


def _event(split_plan_id="plan_a", dataset_snapshot_id=_SNAPSHOT_ID, research_run_id="run_x",
           reason="Audit", **kwargs):
    return build_holdout_access_event(
        split_plan_id=split_plan_id, dataset_snapshot_id=dataset_snapshot_id,
        research_run_id=research_run_id, reason=reason, **kwargs
    )


# ═══════════════════════════════════════════════════════════════════════════════
# A, C. DatasetSplitPlan minimal, référence directe à l'identité dataset réelle
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_dataset_split_plan_minimal():
    """A. Un plan minimal ne nécessite que TRAIN + FINAL_HOLDOUT (VALIDATION/DISCOVERY_OOS
    optionnelles — aucun consommateur réel ne les exploite encore, voir DOMAIN_MODEL.md §12)."""
    plan = _plan()

    assert plan.split_plan_id == "plan_a"
    assert plan.dataset_snapshot_id == _SNAPSHOT_ID
    assert plan.validation is None
    assert plan.discovery_oos is None
    assert plan.created_at  # horodatage auto-rempli


def test_build_dataset_split_plan_with_all_four_zones():
    plan = _plan(
        validation=_boundary("2024-04-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
        discovery_oos=_boundary("2024-06-01T00:00:00+00:00", "2024-09-01T00:00:00+00:00"),
        train=_boundary("2024-01-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"),
    )

    assert plan.validation is not None
    assert plan.discovery_oos is not None


def test_dataset_split_plan_references_real_dataset_identity_by_identifier():
    """C. Référence directe par identifiant réel (le même dataset_snapshot_id qu'AF-DATA/
    ResearchRun) — jamais une DatasetVersion cataloguée inventée."""
    plan = _plan()

    assert plan.dataset_snapshot_id == _SNAPSHOT_ID


@pytest.mark.parametrize("bad_id", [None, "", "   "])
def test_build_dataset_split_plan_requires_a_real_dataset_snapshot_id(bad_id):
    """D. Aucune fausse DatasetVersion cataloguée — mais aussi aucun plan sans identité réelle."""
    with pytest.raises(ValueError):
        _plan(dataset_snapshot_id=bad_id)


@pytest.mark.parametrize("bad_id", ["../escape", "a/b", "a\\b", "..", "", "   "])
def test_build_dataset_split_plan_rejects_unsafe_split_plan_id(bad_id):
    """split_plan_id sert à construire un chemin de fichier (voir split_plan_slug()) — même
    protection path-traversal que research_run_id/experiment_id (AF-R-01)."""
    with pytest.raises(ValueError):
        _plan(split_plan_id=bad_id)


@pytest.mark.parametrize("bad_id", ["plan:a", "plan*a", "plan?a", "plan<a", "plan>a", "plan|a"])
def test_build_dataset_split_plan_rejects_split_plan_id_unsafe_for_windows_filenames(bad_id):
    """Trouvé par MCP Codex (revue globale Track R) : ces caractères passeraient la protection
    path-traversal ci-dessus mais restent invalides comme nom de fichier/dossier Windows.
    REJETÉS (jamais sanitisés — une sanitisation permissive ferait collisionner deux identités
    distinctes, ex. "plan:a" et "plan*a" vers le même slug)."""
    with pytest.raises(ValueError):
        _plan(split_plan_id=bad_id)


# ═══════════════════════════════════════════════════════════════════════════════
# CARDINALITÉ CORRIGÉE — plusieurs DatasetSplitPlan pour le même dataset_snapshot_id
# ═══════════════════════════════════════════════════════════════════════════════


def test_two_different_split_plans_can_share_the_same_dataset_snapshot_id(tmp_path):
    """A (mission corrective). Scénario obligatoire : ResearchRun A (TRAIN=2020-2022,
    FINAL_HOLDOUT=2023) et ResearchRun B (TRAIN=2019-2021, VALIDATION=2022,
    FINAL_HOLDOUT=2023-2024) découpent différemment EXACTEMENT le même snapshot — légitime,
    Track R répond "quelle portion CE ResearchRun a utilisée", pas une propriété du snapshot
    lui-même. Aucun nouveau content_hash/snapshot_id, aucune copie de données."""
    plan_a = _plan(
        split_plan_id="plan_run_a",
        train=_boundary("2020-01-01T00:00:00+00:00", "2022-01-01T00:00:00+00:00"),
        final_holdout=_boundary("2023-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00"),
    )
    plan_b = _plan(
        split_plan_id="plan_run_b",
        train=_boundary("2019-01-01T00:00:00+00:00", "2021-01-01T00:00:00+00:00"),
        validation=_boundary("2022-01-01T00:00:00+00:00", "2023-01-01T00:00:00+00:00"),
        final_holdout=_boundary("2023-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
    )

    path_a = save_dataset_split_plan(tmp_path / "plan_a.json", plan_a)  # B. ne doit jamais lever
    path_b = save_dataset_split_plan(tmp_path / "plan_b.json", plan_b)  # C. ni collisionner

    loaded_a = load_dataset_split_plan(path_a)
    loaded_b = load_dataset_split_plan(path_b)
    assert loaded_a.split_plan_id != loaded_b.split_plan_id  # B. identités distinctes et stables
    # D. les deux continuent de référencer exactement le même dataset_snapshot_id.
    assert loaded_a.dataset_snapshot_id == loaded_b.dataset_snapshot_id == _SNAPSHOT_ID
    assert loaded_a.train.start == "2020-01-01T00:00:00+00:00"
    assert loaded_b.train.start == "2019-01-01T00:00:00+00:00"


def test_holdout_access_event_is_attributable_to_the_correct_plan_when_snapshot_is_shared(
    tmp_path,
):
    """E, F (mission corrective). Deux plans partagent le même snapshot ; un HoldoutAccessEvent
    doit être attribuable SANS AMBIGUÏTÉ au bon plan/FINAL_HOLDOUT — l'audit ne doit jamais
    confondre les deux."""
    events_dir_a = tmp_path / "plan_run_a" / "holdout_access"
    events_dir_b = tmp_path / "plan_run_b" / "holdout_access"

    event_for_a = _event(split_plan_id="plan_run_a", research_run_id="run_a", reason="Audit A")
    save_holdout_access_event(events_dir_a, event_for_a)

    # F. le plan B, partageant le même snapshot, ne montre AUCUN événement halte à lui — l'audit
    # ne confond pas les deux plans juste parce qu'ils partagent un dataset_snapshot_id.
    assert has_holdout_access_events(events_dir_a) is True
    assert has_holdout_access_events(events_dir_b) is False

    loaded = list_holdout_access_events(events_dir_a)[0]
    assert loaded.split_plan_id == "plan_run_a"
    assert loaded.dataset_snapshot_id == _SNAPSHOT_ID  # toujours référencé directement, en plus


# ═══════════════════════════════════════════════════════════════════════════════
# E, F, H. Zones explicites (pas un dict opaque), bornes non ambiguës
# ═══════════════════════════════════════════════════════════════════════════════


def test_split_boundary_is_an_explicit_small_type_not_an_opaque_dict():
    """E. Une zone a un invariant propre (start < end) : type explicite `SplitBoundary`, pas un
    dict métier opaque."""
    boundary = build_split_boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00")

    assert isinstance(boundary, SplitBoundary)
    assert boundary.start == "2024-01-01T00:00:00+00:00"
    assert boundary.end == "2024-06-01T00:00:00+00:00"


def test_split_boundary_rejects_end_before_or_equal_to_start():
    """F. Bornes non ambiguës : end doit strictement suivre start (intervalle [start, end))."""
    with pytest.raises(ValueError):
        build_split_boundary("2024-06-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00")

    with pytest.raises(ValueError):
        build_split_boundary("2024-01-01T00:00:00+00:00", "2024-01-01T00:00:00+00:00")


def test_split_boundary_requires_offset_aware_utc_timestamps():
    """H. Timestamps non ambigus : ISO-8601 offset-aware obligatoire, jamais un datetime naïf
    (même discipline qu'AF-R-01/02 pour created_at/completed_at)."""
    with pytest.raises(ValueError):
        build_split_boundary("2024-01-01T00:00:00", "2024-06-01T00:00:00+00:00")  # start naïf

    with pytest.raises(ValueError):
        build_split_boundary("not-a-date", "2024-06-01T00:00:00+00:00")


# ═══════════════════════════════════════════════════════════════════════════════
# G. Chronologie / non-chevauchement des zones présentes
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_dataset_split_plan_rejects_overlapping_zones():
    """G. Les zones présentes doivent rester chronologiques et non chevauchantes entre elles."""
    with pytest.raises(ValueError):
        _plan(
            train=_boundary("2024-01-01T00:00:00+00:00", "2024-07-01T00:00:00+00:00"),
            final_holdout=_boundary("2024-06-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00"),
        )


def test_build_dataset_split_plan_rejects_out_of_order_intermediate_zones():
    """G. Même invariant appliqué aux zones intermédiaires optionnelles."""
    with pytest.raises(ValueError):
        _plan(
            train=_boundary("2024-01-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"),
            discovery_oos=_boundary("2024-04-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
            validation=_boundary("2024-06-01T00:00:00+00:00", "2024-08-01T00:00:00+00:00"),
            final_holdout=_boundary("2024-09-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00"),
        )


def test_build_dataset_split_plan_allows_gaps_between_zones():
    """G (précision) : un écart entre deux zones (marge tampon anti-contamination) est autorisé —
    la couverture complète du dataset n'est pas exigée."""
    plan = _plan(
        train=_boundary("2024-01-01T00:00:00+00:00", "2024-03-01T00:00:00+00:00"),
        final_holdout=_boundary("2024-09-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00"),
    )

    assert plan.train.end != plan.final_holdout.start  # écart toléré, pas une erreur


def test_build_dataset_split_plan_allows_touching_zones():
    """Des zones adjacentes exactement contiguës ([start,end) demi-ouvert) restent valides — pas
    un chevauchement."""
    plan = _plan(
        train=_boundary("2024-01-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
        final_holdout=_boundary("2024-06-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00"),
    )

    assert plan.train.end == plan.final_holdout.start


# ═══════════════════════════════════════════════════════════════════════════════
# I, J, K. Persistance : immutabilité, round-trip strict, fichier existant
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_and_load_dataset_split_plan_round_trips(tmp_path):
    """J. Persistance -> relecture strictement cohérente, y compris les zones imbriquées
    (SplitBoundary) — pas seulement les champs plats."""
    plan = _plan(
        train=_boundary("2024-01-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"),
        validation=_boundary("2024-04-01T00:00:00+00:00", "2024-06-01T00:00:00+00:00"),
        final_holdout=_boundary("2024-09-01T00:00:00+00:00", "2024-12-01T00:00:00+00:00"),
    )
    path = save_dataset_split_plan(tmp_path / "split_plan.json", plan)

    loaded = load_dataset_split_plan(path)

    assert loaded == plan
    assert isinstance(loaded.train, SplitBoundary)
    assert isinstance(loaded.validation, SplitBoundary)
    assert loaded.discovery_oos is None


def test_load_dataset_split_plan_tolerates_missing_file(tmp_path):
    assert load_dataset_split_plan(tmp_path / "does_not_exist.json") is None


def test_load_dataset_split_plan_tolerates_corrupted_file(tmp_path):
    path = tmp_path / "corrupted.json"
    path.write_text("{not valid json", encoding="utf-8")

    assert load_dataset_split_plan(path) is None


def test_save_dataset_split_plan_never_overwrites_an_existing_plan(tmp_path):
    """I. Un DatasetSplitPlan est immuable — un seul plan par split_plan_id, la première écriture
    fait foi (un second plan pour le MÊME split_plan_id serait lui-même un vecteur de fuite ; un
    second plan pour un split_plan_id DIFFÉRENT référençant le même snapshot est légitime, voir
    test_two_different_split_plans_can_share_the_same_dataset_snapshot_id)."""
    plan = _plan(split_plan_id="plan_a")
    path = tmp_path / "split_plan.json"
    save_dataset_split_plan(path, plan)

    other_plan = _plan(
        split_plan_id="plan_a",  # même split_plan_id -> collision réelle, doit être rejetée
        train=_boundary("2024-01-01T00:00:00+00:00", "2024-02-01T00:00:00+00:00"),
        final_holdout=_boundary("2024-03-01T00:00:00+00:00", "2024-04-01T00:00:00+00:00"),
    )
    with pytest.raises(FileExistsError):
        save_dataset_split_plan(path, other_plan)

    # K. Le contenu original reste inchangé — jamais d'écrasement silencieux.
    assert load_dataset_split_plan(path).train.end == "2024-06-01T00:00:00+00:00"


# ═══════════════════════════════════════════════════════════════════════════════
# L, M, N, O, P, Q. HoldoutAccessEvent minimal
# ═══════════════════════════════════════════════════════════════════════════════


def test_build_holdout_access_event_minimal():
    """L. Création d'un événement minimal."""
    event = _event(reason="Validation finale du Champion avant publication")

    assert event.split_plan_id == "plan_a"
    assert event.dataset_snapshot_id == _SNAPSHOT_ID
    assert event.research_run_id == "run_x"
    assert event.reason == "Validation finale du Champion avant publication"
    assert event.accessed_at  # O, horodatage auto-rempli


def test_holdout_access_event_research_run_id_is_direct():
    """M. research_run_id direct — aucun champ experiment_id dupliqué (dérivable du ResearchRun
    référencé, même principe que "référence par identifiant" déjà établi AF-R-01)."""
    event = _event()

    assert not hasattr(event, "experiment_id")


def test_holdout_access_event_dataset_identity_is_direct():
    """N. dataset_snapshot_id référencé DIRECTEMENT sur l'événement, EN PLUS de split_plan_id —
    pas seulement via une jointure, pour un audit sans jointure implicite (exigé explicitement par
    DOMAIN_MODEL.md §12 — jamais remplacé par split_plan_id, seulement complété)."""
    event = _event()

    assert event.dataset_snapshot_id == _SNAPSHOT_ID
    assert event.split_plan_id == "plan_a"


def test_holdout_access_event_accessed_at_is_offset_aware_utc():
    """O. Timestamp UTC explicite, ISO-8601 offset-aware — jamais un datetime naïf."""
    event = _event()

    parsed = datetime.fromisoformat(event.accessed_at)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize("bad_reason", [None, "", "   "])
def test_build_holdout_access_event_requires_a_reason(bad_reason):
    """P. reason obligatoire — un événement d'audit sans motif énoncé viderait le journal de son
    utilité (contrairement à Experiment.hypothesis, qui reste optionnel)."""
    with pytest.raises(ValueError):
        _event(reason=bad_reason)


def test_build_holdout_access_event_locked_state_is_declarative_not_a_state_machine():
    """Q. locked_state capture ce que l'accédant déclare avoir constaté à l'instant T — deux
    valeurs seulement, jamais une state machine complexe."""
    event_locked = _event(locked_state="locked")
    event_unlocked = _event(research_run_id="run_y", locked_state="unlocked")

    assert event_locked.locked_state == "locked"
    assert event_unlocked.locked_state == "unlocked"

    with pytest.raises(ValueError):
        _event(locked_state="maybe")


# ═══════════════════════════════════════════════════════════════════════════════
# Q, R, S. Immutabilité append-only — plusieurs événements, jamais réécriture
# ═══════════════════════════════════════════════════════════════════════════════


def test_save_and_load_holdout_access_event_round_trips(tmp_path):
    """S. Persistance -> relecture strictement cohérente."""
    event = _event(reason="Audit final")
    path = save_holdout_access_event(tmp_path, event)

    loaded = load_holdout_access_event(path)

    assert loaded == event


def test_build_holdout_access_event_rejects_a_research_run_id_unsafe_for_windows_filenames():
    """Trouvé en revue `/code-review` Standards, puis affiné par MCP Codex : `research_run_id`
    passait `validate_identifier()` (rejette seulement `/`, `\\`, `..`, vide) mais pas
    `:`/`*`/`?`/`<`/`>`/`|`, invalides comme nom de fichier Windows. **Correction (MCP Codex)** :
    sanitiser silencieusement serait une transformation à PERTE — "run:a" et "run*a" produiraient
    le même nom de fichier, un vrai risque de collision d'identité. `validate_portable_identifier()`
    REJETTE désormais ces caractères au lieu de les transformer."""
    with pytest.raises(ValueError):
        _event(research_run_id="run:2026*bad?")


def test_build_holdout_access_event_rejects_a_caller_supplied_event_id_unsafe_for_windows():
    """Trouvé en revue globale Track R : un `event_id` fourni explicitement par l'appelant
    (`build_holdout_access_event()` l'accepte en paramètre optionnel, pas seulement l'UUID4 par
    défaut) contenant `:`/`*`/`?` doit être REJETÉ (même raisonnement que ci-dessus — jamais
    sanitisé silencieusement)."""
    with pytest.raises(ValueError):
        _event(event_id="evt:2026*bad?")


def test_two_events_with_the_same_timestamp_and_research_run_id_never_collide(tmp_path):
    """Trouvé par MCP Codex (revue indépendante AF-R-03) : le nom de fichier dérivé uniquement de
    accessed_at+research_run_id peut entrer en collision si deux événements distincts partagent
    exactement le même timestamp (résolution d'horloge grossière, ou deux accès la même seconde) —
    risque réel de perte silencieuse d'événement pour un composant dont le but même est de n'en
    perdre aucun. Chaque événement doit rester distinctement persisté."""
    same_timestamp = "2024-01-01T00:00:00+00:00"
    first = _event(research_run_id="run_a", reason="Premier accès", accessed_at=same_timestamp)
    second = _event(
        research_run_id="run_a", reason="Second accès distinct", accessed_at=same_timestamp,
    )

    save_holdout_access_event(tmp_path, first)
    save_holdout_access_event(tmp_path, second)  # ne doit jamais lever FileExistsError ici

    events = list_holdout_access_events(tmp_path)
    reasons = {e.reason for e in events}
    assert len(events) == 2
    assert reasons == {"Premier accès", "Second accès distinct"}


def test_holdout_access_event_id_survives_persistence_round_trip(tmp_path):
    event = _event()
    assert event.event_id  # auto-généré, jamais vide

    path = save_holdout_access_event(tmp_path, event)
    loaded = load_holdout_access_event(path)

    assert loaded.event_id == event.event_id


def test_second_holdout_access_produces_a_new_event_never_overwrites_the_first(tmp_path):
    """Q, R. Un deuxième accès (même dataset, même ou différent ResearchRun) produit un NOUVEL
    événement — jamais l'écrasement du premier (append-only)."""
    first = _event(
        research_run_id="run_a", reason="Première consultation",
        accessed_at="2024-01-01T00:00:00+00:00",
    )
    second = _event(
        research_run_id="run_b", reason="Deuxième consultation",
        accessed_at="2024-01-02T00:00:00+00:00",
    )

    save_holdout_access_event(tmp_path, first)
    save_holdout_access_event(tmp_path, second)

    events = list_holdout_access_events(tmp_path)
    reasons = {e.reason for e in events}
    assert len(events) == 2
    assert reasons == {"Première consultation", "Deuxième consultation"}


# ═══════════════════════════════════════════════════════════════════════════════
# T, U. API d'audit honnête — has_holdout_access_events(), jamais is_untouched()
# ═══════════════════════════════════════════════════════════════════════════════


def test_has_holdout_access_events_is_false_when_none_recorded(tmp_path):
    assert has_holdout_access_events(tmp_path) is False


def test_has_holdout_access_events_is_true_after_at_least_one_event(tmp_path):
    """T, U. La présence d'au moins un événement est détectable — aucun rapport futur ne peut
    ignorer un événement existant pour qualifier un holdout de "sain"."""
    event = _event()
    save_holdout_access_event(tmp_path, event)

    assert has_holdout_access_events(tmp_path) is True


def test_no_is_untouched_function_exists():
    """U (garde-fou anti-sur-promesse). Le module ne fournit délibérément aucune fonction
    `is_untouched()` — notre audit ne peut prouver qu'une absence d'accès enregistré dans SES
    propres fichiers, jamais une absence physique absolue."""
    import dataset_split as module

    assert not hasattr(module, "is_untouched")


# ═══════════════════════════════════════════════════════════════════════════════
# Slug — split_plan_id doit déjà être portable (rejeté, jamais sanitisé, voir MCP Codex)
# ═══════════════════════════════════════════════════════════════════════════════


def test_split_plan_slug_returns_the_identifier_unchanged_when_already_portable():
    """Un split_plan_id déjà portable (alphanumérique/`_`/`.`/`-`) traverse `split_plan_slug()`
    inchangé — plus de transformation à perte depuis la correction MCP Codex (voir docstring du
    module) : le slug EST l'identifiant, jamais une version altérée de celui-ci."""
    assert split_plan_slug("plan_v2.1") == "plan_v2.1"


@pytest.mark.parametrize("bad_id", ["../escape", "", "plan:v2", "plan*v2"])
def test_split_plan_slug_rejects_unsafe_or_empty_identity(bad_id):
    """Caractères de traversal ET caractères invalides sous Windows (`:`, `*`...) sont REJETÉS,
    jamais sanitisés (voir docstring du module — sanitiser serait une transformation à perte,
    risque de collision d'identité)."""
    with pytest.raises(ValueError):
        split_plan_slug(bad_id)


# ═══════════════════════════════════════════════════════════════════════════════
# V, W, X, Y, Z. Compatibilité — legacy, AF-R-01/02, aucune dépendance interdite
# ═══════════════════════════════════════════════════════════════════════════════


def test_missing_split_plan_is_a_normal_legacy_state(tmp_path):
    """V. Un dataset sans DatasetSplitPlan reste un état normal (aucun plan n'est jamais créé
    automatiquement) — lecture tolérante, aucune exception."""
    assert load_dataset_split_plan(tmp_path / "no_plan_here.json") is None


def test_missing_holdout_access_events_is_a_normal_legacy_state(tmp_path):
    """W. Un dataset sans HoldoutAccessEvent reste un état normal."""
    assert list_holdout_access_events(tmp_path / "no_events_dir") == []
    assert has_holdout_access_events(tmp_path / "no_events_dir") is False


def test_dataset_split_module_has_no_database_or_ui_dependency():
    """Z. Aucun import PostgreSQL/Redis/Streamlit — persistance fichier pure, comme
    research_run.py."""
    import dataset_split as module

    import_lines = "\n".join(
        line for line in open(module.__file__, encoding="utf-8")
        if line.strip().startswith(("import ", "from "))
    ).lower()

    assert "psycopg2" not in import_lines
    assert "sqlalchemy" not in import_lines
    assert "streamlit" not in import_lines
    assert "redis" not in import_lines
    assert "celery" not in import_lines
