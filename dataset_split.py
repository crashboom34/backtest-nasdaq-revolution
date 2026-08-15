"""
dataset_split.py — DatasetSplitPlan / HoldoutAccessEvent, fondations (AF-R-03).

Track R (Reproducibility & Research Foundations), après `AF-R-01`/`AF-R-02` validés localement.
Voir `docs/architecture/DOMAIN_MODEL.md` §12 ("Dataset splits et Final Holdout / Lockbox") pour le
concept d'origine, et la note "Résolution AF-R-03" ajoutée dans ce même paragraphe pour les
décisions de modélisation prises ici (`/domain-modeling` réellement invoqué).

**Famille de concepts distincte de `research_run.py`** : `Experiment`/`ResearchRun` décrivent une
*exécution de recherche* ; `DatasetSplitPlan`/`HoldoutAccessEvent` décrivent l'*audit/provenance
d'un dataset* — structurellement différent, module séparé (voir `/codebase-design`).

**Ne pas confondre avec le split train/test EXISTANT** (`optimizer.py::TrainTestConfig`,
`compute_split_dates()`) : ce mécanisme, réel et déjà branché dans l'Optimizer, sépare les données
d'UNE optimisation en 2 zones (train/test) pour l'anti-overfitting pendant l'exécution elle-même.
`DatasetSplitPlan` est un concept **différent** : une partition **déclarative, à 4 zones**
(`TRAIN`/`VALIDATION`/`DISCOVERY_OOS`/`FINAL_HOLDOUT`) d'une version de dataset, à but d'audit/
provenance Track R — **non consommée par l'engine/Optimizer**, aucun couplage avec
`TrainTestConfig`. `CONTEXT.md` documente déjà explicitement l'ambiguïté du mot "split" dans ce
dépôt — les noms `DatasetSplitPlan`/`SplitBoundary`/`SplitZone` de ce module désignent toujours le
nouveau concept d'audit, jamais le split train/test existant.

Identité dataset — pas de fausse `DatasetVersion` cataloguée : `dataset_snapshot_id` réutilise
exactement le champ déjà accepté sur `ResearchRun` (`AF-R-01`), lui-même produit par `AF-DATA`
(forme `"local_csv:sha256:<hash>"`). Aucune `DatasetVersionRepository`/table/registre créé ici.

**Cardinalité corrigée (revue corrective, 2026-08-15)** : une première version de ce module
identifiait `DatasetSplitPlan` PAR son `dataset_snapshot_id` (un seul plan par snapshot). **C'était
une erreur de modélisation, corrigée ici** — voir DOMAIN_MODEL.md §12 pour la preuve textuelle
complète. En bref : `DatasetSnapshot` (Track DATA — "quelle version de données existe ?") et
`DatasetSplitPlan` (Track R — "quelle portion **CE ResearchRun** a utilisée ?", frontière déjà
établie par `MASTER_ROADMAP.md`) sont des identités **distinctes**. Le même `dataset_snapshot_id`
peut légitimement servir de base à **plusieurs** `DatasetSplitPlan` (deux `ResearchRun` choisissant
des découpages temporels différents du même CSV source, sans jamais recalculer `content_hash`/
`snapshot_id` ni copier les données). `DatasetSplitPlan` est donc identifié par un `split_plan_id:
str` **propre** (choisi par l'appelant, même motif que `research_run_id`/`experiment_id` — pas un
UUID auto-généré comme `HoldoutAccessEvent.event_id`, ni un hash canonique du contenu : un plan de
recherche est une intention nommable, pas un fait technique anonyme) ; `dataset_snapshot_id` reste
un **champ obligatoire** du plan (référence directe), mais n'est plus sa clé de stockage.

**Portée de ce ticket ("fondations")** : `TRAIN`/`FINAL_HOLDOUT` sont obligatoires ;
`VALIDATION`/`DISCOVERY_OOS` restent optionnelles tant qu'aucun consommateur réel (Walk-Forward,
Discovery — hors scope ici) ne les exploite. `HoldoutAccessEvent` référence **à la fois**
`split_plan_id` (désambiguïse QUEL plan/`FINAL_HOLDOUT` précis a été consulté, maintenant que
plusieurs plans peuvent partager un même snapshot) **et** `dataset_snapshot_id` directement (jamais
seulement via `split_plan_id` — exigé par DOMAIN_MODEL.md §12 "pour un audit sans jointure
implicite" ; ces deux champs sont **asserted par l'appelant**, jamais croisés/validés l'un contre
l'autre ici — une divergence serait une donnée incohérente, pas silencieusement résolue, voir MCP
Codex) et `research_run_id` (jamais `experiment_id` dupliqué, dérivable du `ResearchRun`
référencé). `reason` est **obligatoire** (contrairement à `Experiment.hypothesis`) : un événement
d'audit sans motif énoncé viderait le journal de son utilité. `locked_state` est purement
déclaratif (`"locked"`/`"unlocked"`, ce que l'accédant constate à l'instant T) — **pas** une state
machine, **pas** un contrôle d'accès technique : ce module ne bloque jamais un accès, il le rend
seulement observable.

**`ResearchRun` ne référence PAS `split_plan_id`** — prématuré, aucun pipeline réel ne consomme
encore le split (voir "hors scope" plus bas). La future traçabilité "quel `ResearchRun` a utilisé
quel plan" passera vraisemblablement par `HoldoutAccessEvent.split_plan_id`/`research_run_id`
plutôt que par un nouveau champ sur `ResearchRun` — décision différée explicitement, pas oubliée.

**API "untouched" honnête** : `has_holdout_access_events(events_dir)` (constat factuel — "au moins
un événement existe dans CE répertoire d'audit"), jamais `is_untouched()` — impossible de prouver
une absence d'accès humain au-delà de nos propres fichiers. **Portée explicite (précision MCP
Codex)** : `events_dir` est désormais typiquement **scopé par plan** (plusieurs plans pouvant
partager un snapshot, "au moins un événement pour CE snapshot" ne serait plus une question
univoque) — l'appelant doit passer le répertoire du plan précis dont il veut l'état, jamais un
répertoire partagé entre plans distincts.

**Portabilité de chemin ET absence de collision d'identité (revue globale Track R, MCP Codex,
2026-08-15)** : `split_plan_id`/`research_run_id`/`event_id` (identifiants choisis par l'appelant
ou auto-générés, qui finissent en clé de stockage) valident via `validate_portable_identifier()`
— **rejette** (ne transforme jamais) tout caractère hors `[A-Za-z0-9_.-]`, en plus des règles de
`validate_identifier()` (`/`, `\\`, `..`, vide). Une sanitisation permissive de type
`filesystem_safe()` (remplacer les caractères interdits par `_`) serait une transformation à
PERTE, non injective : `"plan:a"` et `"plan*a"` produiraient le même slug, un vrai risque de
collision d'identité pour un système qui revendique l'immutabilité par identifiant — pas un simple
problème de traversal. `filesystem_safe()` reste utilisée uniquement pour `accessed_at` (un
timestamp ISO-8601, jamais lui-même une clé de stockage — l'unicité vient de `event_id`, lui
strictement validé). `dataset_snapshot_id` ne sert plus jamais à construire un chemin
(simplification directe de la correction de cardinalité — il ne vit plus que dans le contenu
JSON). Structure de fichiers **recommandée** pour une future intégration (documentée ici, non
câblée — voir plus bas "hors scope") : `results/dataset_splits/<split_plan_id>/split_plan.json`
et `.../holdout_access/<horodatage-slug>_<research_run_id>_<event_id>.json` (un fichier par
événement, jamais un JSONL en append — cohérent avec le motif atomique déjà établi : écriture
fichier temporaire + `os.replace()`, qui suppose une écriture = un fichier neuf, pas un append
concurrent sans verrou).

**Hors scope explicite de ce ticket** : aucun câblage `job_store.py`/`optimizer_process.py` — ni
`DatasetSplitPlan` ni `HoldoutAccessEvent` ne correspondent à un événement du cycle de vie d'un job
(contrairement à `ResearchRun`, créé une fois par job terminé, un `DatasetSplitPlan` est créé UNE
fois par dataset et un `HoldoutAccessEvent` seulement quand quelqu'un ouvre délibérément le
holdout — aucun des deux ne doit être généré automatiquement à la fin d'un job). Ce module reste
directement testable et appelable, sans point d'intégration pipeline réel pour l'instant.

Même motif que `research_run.py` (dataclasses `frozen`, écriture atomique, lecture tolérante) —
partagé via `atomic_json_store.py` (extrait de `research_run.py` au moment où cette troisième
implémentation aurait sinon dupliqué la même logique une nouvelle fois — Rule of Three ;
`validate_identifier()` y a été déplacée pour la même raison en revue `/code-review`, plutôt que
réimportée depuis `research_run.py` comme symbole privé). `load_dataset_split_plan()` reste
néanmoins une fonction dédiée (pas un simple appel à `load_tolerant()`) : `DatasetSplitPlan` a des
champs dataclass imbriqués (`SplitBoundary`) que la reconstruction générique `cls(**data)` ne
rehydrate pas automatiquement depuis le JSON — elle réutilise `load_json_tolerant()` pour la partie
commune (lecture/parsing tolérant), et ne personnalise que l'étape de reconstruction.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Literal, Optional, Union

from atomic_json_store import (
    filesystem_safe, load_json_tolerant, load_tolerant, save_atomic, validate_portable_identifier,
)

SplitZone = Literal["TRAIN", "VALIDATION", "DISCOVERY_OOS", "FINAL_HOLDOUT"]
_ZONE_ORDER = ("TRAIN", "VALIDATION", "DISCOVERY_OOS", "FINAL_HOLDOUT")


@dataclass(frozen=True)
class SplitBoundary:
    """Frontière `[start, end)` d'une zone — borne de fin exclue (deux zones adjacentes peuvent
    partager exactement `a.end == b.start` sans se chevaucher)."""

    start: str
    end: str


@dataclass(frozen=True)
class DatasetSplitPlan:
    """Partition logique déclarative d'un `dataset_snapshot_id` — voir docstring du module.
    `train`/`final_holdout` obligatoires ; `validation`/`discovery_oos` optionnelles.

    `split_plan_id` : identité **propre** du plan (choisie par l'appelant) — plusieurs plans
    peuvent référencer le même `dataset_snapshot_id` (correction de cardinalité, voir docstring du
    module). `dataset_snapshot_id` reste un champ obligatoire (référence directe), jamais la clé
    de stockage."""

    split_plan_id: str
    dataset_snapshot_id: str
    train: SplitBoundary
    final_holdout: SplitBoundary
    validation: Optional[SplitBoundary]
    discovery_oos: Optional[SplitBoundary]
    created_at: str


@dataclass(frozen=True)
class HoldoutAccessEvent:
    """Fait historique immuable : consultation observée du `FINAL_HOLDOUT` — voir docstring du
    module. Jamais un contrôle d'accès, un journal append-only.

    `event_id` : identifiant unique auto-généré (UUID4), **pas** une donnée métier — sert
    uniquement à garantir l'absence de collision de nom de fichier entre deux événements distincts
    partageant le même `accessed_at`/`research_run_id` (horloge grossière, deux accès la même
    seconde, processus séparés — voir `save_holdout_access_event()`). Trouvé par revue
    indépendante (MCP Codex, 2026-08-15) : `accessed_at + research_run_id` seuls ne suffisent pas
    à garantir l'unicité, un composant dont le but est de n'en perdre aucun ne peut pas se
    permettre ce risque.

    `split_plan_id` : QUEL plan (donc quel `FINAL_HOLDOUT` précis) a été consulté — nécessaire
    depuis que plusieurs `DatasetSplitPlan` peuvent partager un même `dataset_snapshot_id`
    (correction de cardinalité, voir docstring du module). `dataset_snapshot_id` reste EN PLUS,
    direct (jamais remplacé) — les deux champs sont asserted par l'appelant, jamais croisés/
    validés l'un contre l'autre par ce module (confirmé MCP Codex : une divergence serait une
    donnée incohérente à traiter comme telle, pas à résoudre silencieusement ici)."""

    split_plan_id: str
    dataset_snapshot_id: str
    research_run_id: str
    reason: str
    locked_state: str
    accessed_at: str
    event_id: str


def _parse_offset_aware(value: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} doit être un timestamp ISO-8601 valide : {value!r}")
    if parsed.tzinfo is None:
        raise ValueError(
            f"{field_name} doit être offset-aware (UTC explicite, ex. '...+00:00') : {value!r}"
        )
    return parsed


def build_split_boundary(start: str, end: str) -> SplitBoundary:
    """Construit une `SplitBoundary`. `start`/`end` : ISO-8601 offset-aware, `start` doit
    strictement précéder `end` (intervalle `[start, end)`, jamais vide ni inversé)."""
    start_dt = _parse_offset_aware(start, "start")
    end_dt = _parse_offset_aware(end, "end")
    if not start_dt < end_dt:
        raise ValueError(
            f"Une borne doit être chronologique : start ({start!r}) doit strictement précéder "
            f"end ({end!r})."
        )
    return SplitBoundary(start=start, end=end)


def build_dataset_split_plan(
    split_plan_id: str,
    dataset_snapshot_id: str,
    train: SplitBoundary,
    final_holdout: SplitBoundary,
    validation: Optional[SplitBoundary] = None,
    discovery_oos: Optional[SplitBoundary] = None,
    created_at: Optional[str] = None,
) -> DatasetSplitPlan:
    """Construit un `DatasetSplitPlan`. Lève `ValueError` si `split_plan_id` est invalide (voir
    `validate_portable_identifier()`) ou si `dataset_snapshot_id` est absent/vide (aucun plan sans
    identité dataset réelle) ou si les zones présentes ne sont pas chronologiques/non chevauchantes
    entre elles (gaps autorisés, couverture complète non exigée — voir docstring du module).

    Plusieurs plans peuvent référencer le même `dataset_snapshot_id` — c'est `split_plan_id`, pas
    `dataset_snapshot_id`, qui identifie CE plan (correction de cardinalité, voir docstring du
    module)."""
    if not isinstance(dataset_snapshot_id, str) or not dataset_snapshot_id.strip():
        raise ValueError(
            "dataset_snapshot_id est obligatoire pour un DatasetSplitPlan — aucune fausse "
            "DatasetVersion cataloguée n'est créée à sa place (voir DOMAIN_MODEL.md §12)."
        )

    zones = {"TRAIN": train, "VALIDATION": validation, "DISCOVERY_OOS": discovery_oos,
              "FINAL_HOLDOUT": final_holdout}
    present = [(name, zones[name]) for name in _ZONE_ORDER if zones[name] is not None]
    for (name_a, a), (name_b, b) in zip(present, present[1:]):
        if _parse_offset_aware(a.end, f"{name_a}.end") > _parse_offset_aware(b.start, f"{name_b}.start"):
            raise ValueError(
                f"{name_a} (fin {a.end!r}) chevauche {name_b} (début {b.start!r}) — les zones "
                "doivent rester chronologiques et non chevauchantes entre elles."
            )

    return DatasetSplitPlan(
        split_plan_id=validate_portable_identifier(split_plan_id, "split_plan_id"),
        dataset_snapshot_id=dataset_snapshot_id,
        train=train,
        final_holdout=final_holdout,
        validation=validation,
        discovery_oos=discovery_oos,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )


def build_holdout_access_event(
    split_plan_id: str,
    dataset_snapshot_id: str,
    research_run_id: str,
    reason: str,
    locked_state: str = "locked",
    accessed_at: Optional[str] = None,
    event_id: Optional[str] = None,
) -> HoldoutAccessEvent:
    """Construit un `HoldoutAccessEvent`. `reason` obligatoire (chaîne non vide). `locked_state`
    doit être `"locked"` ou `"unlocked"` — déclaratif, jamais recalculé/vérifié techniquement.
    `event_id` auto-généré (UUID4) si non fourni — voir docstring de `HoldoutAccessEvent`.

    `split_plan_id` et `dataset_snapshot_id` sont tous les deux obligatoires et **asserted par
    l'appelant** — ce module ne vérifie pas que `split_plan_id` référence réellement
    `dataset_snapshot_id` (nécessiterait une lecture du plan, hors de la responsabilité d'un
    simple constructeur pur — voir docstring du module)."""
    if not isinstance(dataset_snapshot_id, str) or not dataset_snapshot_id.strip():
        raise ValueError(
            "dataset_snapshot_id est obligatoire pour un HoldoutAccessEvent — référence directe "
            "exigée (voir DOMAIN_MODEL.md §12, audit sans jointure implicite)."
        )
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "reason est obligatoire pour un HoldoutAccessEvent — un événement d'audit sans motif "
            "énoncé viderait le journal de son utilité."
        )
    if locked_state not in ("locked", "unlocked"):
        raise ValueError(f"locked_state doit être 'locked' ou 'unlocked' : {locked_state!r}")

    return HoldoutAccessEvent(
        split_plan_id=validate_portable_identifier(split_plan_id, "split_plan_id"),
        dataset_snapshot_id=dataset_snapshot_id,
        research_run_id=validate_portable_identifier(research_run_id, "research_run_id"),
        reason=reason,
        locked_state=locked_state,
        accessed_at=accessed_at or datetime.now(timezone.utc).isoformat(),
        event_id=validate_portable_identifier(event_id or uuid.uuid4().hex, "event_id"),
    )


def split_plan_slug(split_plan_id: str) -> str:
    """Dérive un nom de fichier/dossier stable à partir de `split_plan_id`. `build_dataset_split_plan()`/
    `build_holdout_access_event()` valident déjà `split_plan_id` via `validate_portable_identifier()`
    (rejette tout caractère hors `[A-Za-z0-9_.-]`, plutôt que de le sanitiser à la façon
    `filesystem_safe()` — une sanitisation permissive serait une transformation à perte, non
    injective : `"plan:a"` et `"plan*a"` produiraient le même slug, un vrai risque de collision
    d'identité, trouvé par MCP Codex). Ce slug est donc déjà l'identifiant lui-même — cette
    fonction ne fait que revalider, en défense en profondeur, au cas où l'appelant aurait construit
    un `DatasetSplitPlan` directement sans passer par `build_dataset_split_plan()`."""
    return validate_portable_identifier(split_plan_id, "split_plan_id")


def save_dataset_split_plan(path: Union[str, Path], plan: DatasetSplitPlan) -> Path:
    """Écriture atomique du `DatasetSplitPlan`. Lève `FileExistsError` si déjà écrit (immuable —
    un seul plan par `split_plan_id`, mais plusieurs plans distincts peuvent référencer le même
    `dataset_snapshot_id`, voir docstring du module)."""
    return save_atomic(path, asdict(plan), "dataset_split_plan")


def load_dataset_split_plan(path: Union[str, Path]) -> Optional[DatasetSplitPlan]:
    """Lecture tolérante avec rehydratation des `SplitBoundary` imbriquées (voir docstring du
    module — `load_tolerant()` générique ne suffit pas pour des champs dataclass imbriqués).
    Réutilise `load_json_tolerant()` pour la partie commune (fichier absent/illisible/invalide ->
    `None`) ; seule la reconstruction finale est spécifique à ce type."""
    data = load_json_tolerant(path)
    if data is None:
        return None
    try:
        return DatasetSplitPlan(
            split_plan_id=data["split_plan_id"],
            dataset_snapshot_id=data["dataset_snapshot_id"],
            train=SplitBoundary(**data["train"]),
            final_holdout=SplitBoundary(**data["final_holdout"]),
            validation=SplitBoundary(**data["validation"]) if data.get("validation") else None,
            discovery_oos=(
                SplitBoundary(**data["discovery_oos"]) if data.get("discovery_oos") else None
            ),
            created_at=data["created_at"],
        )
    except (TypeError, KeyError):
        return None


def _holdout_access_event_filename(event: HoldoutAccessEvent) -> str:
    """`research_run_id`/`event_id` sont déjà validés à la construction via
    `validate_portable_identifier()` (rejette tout caractère hors `[A-Za-z0-9_.-]`, plutôt que de
    sanitiser — voir `build_holdout_access_event()`/`split_plan_slug()` pour la justification
    complète, trouvée par MCP Codex : sanitiser serait une transformation à perte, non injective,
    donc un risque de collision d'identité). **Revalidés ici en défense en profondeur** (précision
    MCP Codex) : rien n'empêche en Python d'instancier `HoldoutAccessEvent(...)` directement, en
    contournant `build_holdout_access_event()` et sa validation — cette fonction est le point
    d'écriture réel, elle ne fait donc jamais confiance aveuglément au contenu de l'objet reçu.
    Seul `accessed_at` (un timestamp ISO-8601, jamais une clé de stockage — l'unicité vient
    d'`event_id`) contient légitimement des caractères comme `:` et a donc encore besoin de
    `filesystem_safe()` ici, uniquement pour la lisibilité du préfixe chronologique du nom de
    fichier."""
    timestamp_slug = filesystem_safe(event.accessed_at)
    research_run_id = validate_portable_identifier(event.research_run_id, "research_run_id")
    event_id = validate_portable_identifier(event.event_id, "event_id")
    return f"{timestamp_slug}_{research_run_id}_{event_id}.json"


def save_holdout_access_event(events_dir: Union[str, Path], event: HoldoutAccessEvent) -> Path:
    """Écriture atomique d'UN `HoldoutAccessEvent` dans `events_dir` (un fichier par événement —
    append-only : un deuxième accès crée un nouveau fichier, jamais une réécriture)."""
    path = Path(events_dir) / _holdout_access_event_filename(event)
    return save_atomic(path, asdict(event), "holdout_access_event")


def load_holdout_access_event(path: Union[str, Path]) -> Optional[HoldoutAccessEvent]:
    return load_tolerant(path, HoldoutAccessEvent)


def list_holdout_access_events(events_dir: Union[str, Path]) -> List[HoldoutAccessEvent]:
    """Liste tous les `HoldoutAccessEvent` valides d'`events_dir`, triés par nom de fichier
    (donc chronologiquement, grâce à l'horodatage en préfixe). Répertoire absent -> liste vide,
    jamais d'exception (même état "legacy normal" qu'un fichier absent)."""
    events_path = Path(events_dir)
    if not events_path.is_dir():
        return []
    events = []
    for file in sorted(events_path.glob("*.json")):
        event = load_holdout_access_event(file)
        if event is not None:
            events.append(event)
    return events


def has_holdout_access_events(events_dir: Union[str, Path]) -> bool:
    """Constat factuel — "au moins un événement existe dans CE répertoire d'audit". **Jamais**
    `is_untouched()` : une absence retournée signifie "aucune consultation enregistrée dans
    l'audit Track R", jamais une garantie physique absolue (voir docstring du module,
    DOMAIN_MODEL.md invariant §18 point 7).

    **Portée (précision MCP Codex, correction de cardinalité)** : `events_dir` est typiquement
    scopé par `split_plan_id`, pas par `dataset_snapshot_id` — plusieurs plans distincts pouvant
    partager un snapshot, l'appelant doit passer le répertoire du plan précis qu'il audite."""
    return len(list_holdout_access_events(events_dir)) > 0
