"""
research_run.py — Experiment / ResearchRun, schéma minimal + stockage fichier (AF-R-01).

Track R (Reproducibility & Research Foundations), démarré après `GATE DATA = PASS`
(voir docs/roadmap/EPICS_AND_TICKETS.md, AF-R-01). Persistance fichier pure — aucune base de
données (PostgreSQL/Redis restent `Proposed`/hors scope), aucune UI.

Distinction de domaine (DOMAIN_MODEL.md §7, PROPOSED) :
- `Experiment` : conteneur **durable** — une ligne de recherche nommée (`hypothesis` optionnelle
  en texte libre), peut regrouper plusieurs `ResearchRun`. Ne vit PAS dans un seul job directory
  (par nature, il en regroupe potentiellement plusieurs) — persisté séparément.
- `ResearchRun` : exécution **concrète, immuable**. Représente un run déjà terminé — pas de champ
  de lifecycle (CREATED/RUNNING/...) : l'existence même du fichier signifie "ce run est terminé",
  exactement comme `data_manifest.json` (écrit uniquement en fin de job, jamais en cours
  d'exécution — `progress.json`, déjà existant, couvre l'état "en cours").

Référence à l'identité dataset (AF-DATA) : `ResearchRun.dataset_snapshot_id` porte UNIQUEMENT la
chaîne identifiante produite par AF-DATA (ex. `"local_csv:sha256:<hash>"`) — jamais une copie des
autres champs de provenance (`period_start`/`period_end`/`source_timeframe`), qui restent la
seule responsabilité de `data_manifest.json`. Référence par identifiant, pas par valeur — même
principe déjà établi dans DOMAIN_MODEL.md (`ResearchRun` référence un `content_hash` exact, pas
une copie du catalogue).

**Invariant obligatoire (revue AF-R-01, 2026-08-15)** : `dataset_snapshot_id` est **obligatoire**
pour construire un `ResearchRun` via `build_research_run()`. Fondement : (1) le critère
d'acceptation du ticket AF-R-01 lui-même (`EPICS_AND_TICKETS.md`) — "Un ResearchRun référence un
DatasetVersion... par identifiant" —, formulé sans condition, jamais "si disponible" ; (2)
DOMAIN_MODEL.md ligne 163, même formulation sans condition : "un ResearchRun historique référence
le content_hash exact utilisé au moment de l'expérience". **Précision (revue croisée `/code-review`
Spec, 2026-08-15)** : l'invariant §18.2 ("Un ResearchRun référence un ResearchScope figé") cité
dans une version antérieure de ce commentaire porte sur un concept différent (`ResearchScope`,
périmètre de recherche — pas l'identité dataset) et a été retiré d'ici, c'était une citation
inexacte. Noter aussi que le tableau d'invariants de DOMAIN_MODEL.md où figure ce point est
lui-même marqué `PROPOSED TARGET`, pas `Accepted` — cohérent avec tout le schéma Experiment/
ResearchRun de ce fichier, lui aussi `PROPOSED` (voir DOMAIN_MODEL.md §7), et avec l'autorisation
explicite de l'utilisateur (revue AF-R-01, 2026-08-15, §3) de rendre ce point précis obligatoire.

Un `ResearchRun` sans identité dataset ne serait pas un record scientifique reproductible — ce
n'est pas la même chose que l'absence de `ResearchRun` (jobs legacy, compatible et inchangée : voir
`job_store.write_research_run()`, qui ne fait rien tant qu'`experiment_id` n'est pas fourni).

Même motif que `market_data/backtest_manifest.py` : dataclasses `frozen`, écriture atomique
(fichier temporaire + `os.replace()`), jamais écrasées (`FileExistsError` explicite), lecture
tolérante (`None` si absent/invalide, jamais d'exception). **Revue AF-R-03 (2026-08-15)** :
l'implémentation de ce motif (`save_atomic`/`load_tolerant`) et la validation d'identifiants
(`validate_identifier`) ont été extraites vers `atomic_json_store.py` — troisième implémentation
quasi identique sur le point d'apparaître dans `dataset_split.py`, Rule of Three. Comportement
strictement inchangé ici, seul l'import source a changé.

**Revue globale Track R (MCP Codex, 2026-08-15)** : `experiment_id`/`research_run_id` valident
désormais via `validate_portable_identifier()` (rejette tout caractère hors `[A-Za-z0-9_.-]`), pas
seulement `validate_identifier()` (path-traversal). Trouvaille : `experiment_id`/`research_run_id`
finissent en clé de stockage (`experiments/<experiment_id>.json`, noms de fichiers d'événements
Track R) — une sanitisation permissive (`filesystem_safe()`, remplacer les caractères interdits
par `_`) serait une transformation à PERTE, non injective : `"exp:a"` et `"exp*a"` produiraient
tous deux `"exp_a"`, un vrai risque de collision d'identité pour un système immuable. Rejeter
strictement (au lieu de sanitiser) élimine ce risque à la source.

**AF-R-02 (2026-08-15) — capture git_sha / seed / engine_version** : chaque `ResearchRun` capture
désormais trois informations d'identité d'exécution, pour répondre après coup à "quelle version
exacte du logiciel et quelle graine ont produit ce run ?" :

- `git_sha: Optional[str]` — commit Git détecté **automatiquement**, en réutilisant tel quel
  `market_data.backtest_manifest._current_git_commit()` (mécanisme déjà existant, PAS dupliqué —
  même sentinelle `git_sha="auto"` par défaut / `repo_dir` explicite que
  `build_backtest_manifest()`, pour la même raison de testabilité : passer `git_sha=None`
  explicitement désactive la détection, sans dépendre du vrai SHA de la machine). Reste `None`
  honnêtement si Git est indisponible (dossier hors dépôt, `git` absent, timeout) — jamais
  d'exception, jamais une fausse preuve de reproductibilité inventée à la place.
- `seed: Optional[int]` — **optionnel**, jamais généré implicitement (pas de `random.randint`/
  `time.time()`/`hash()` par défaut caché). DOMAIN_MODEL.md (ligne 611) qualifie déjà le seed de
  "lorsque applicable" — une recherche déterministe (single backtest, grid search) n'a
  légitimement aucun seed ; seule une méthode stochastique future (Random Search, algorithme
  génétique — hors scope AF-R-02) en aurait un réel. `build_research_run()` ne fait qu'enregistrer
  la valeur fournie par l'appelant, jamais en inventer une.
- `engine_version: str` — réutilise directement `market_data.backtest_manifest.ENGINE_VERSION`
  comme valeur par défaut (même constante, pas une deuxième source de vérité dupliquée).

**Working tree dirty (audité, non traité)** : `git_sha` identifie `HEAD`, pas nécessairement les
modifications locales non commitées — c'était le cas réel de ce dépôt pendant tout le
développement de Track R, resté volontairement non commité jusqu'à son checkpoint final
(`90e3e29c4c994c4bb54e571240a4121d5d2b16ee`, poussé sur `origin/master`). La limite générale reste
valable pour tout futur travail non commité au-dessus de ce checkpoint. AF-R-02 n'ajoute PAS de
champ `git_dirty`/snapshot du working tree/hash de patch :
`BacktestManifest.git_commit`, le précédent direct que ce ticket réutilise, n'a jamais eu ce champ
non plus malgré la même limite théorique — rester cohérent avec ce précédent plutôt que
sur-construire. Limite documentée, pas résolue silencieusement.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union

from atomic_json_store import load_tolerant, save_atomic, validate_portable_identifier
from market_data.backtest_manifest import ENGINE_VERSION, _current_git_commit


@dataclass(frozen=True)
class Experiment:
    """Conteneur durable d'une ligne de recherche — voir docstring du module."""

    experiment_id: str
    hypothesis: Optional[str]
    created_at: str


@dataclass(frozen=True)
class ResearchRun:
    """Exécution concrète et immuable d'un `Experiment` — voir docstring du module.

    `dataset_snapshot_id` : référence par identifiant vers l'identité dataset produite par
    AF-DATA (`snapshot_id` de `data_manifest.json`), jamais une copie des autres champs de
    provenance. **Obligatoire** — un `ResearchRun` réel référence toujours une identité dataset
    (voir invariant du module ci-dessus) ; `build_research_run()` refuse de construire une
    instance sans elle.
    """

    research_run_id: str
    experiment_id: str
    dataset_snapshot_id: str
    git_sha: Optional[str]
    seed: Optional[int]
    engine_version: str
    completed_at: str


def build_experiment(
    experiment_id: str,
    hypothesis: Optional[str] = None,
    created_at: Optional[str] = None,
) -> Experiment:
    """Construit un `Experiment`. `created_at` auto-rempli (UTC) si non fourni."""
    return Experiment(
        experiment_id=validate_portable_identifier(experiment_id, "experiment_id"),
        hypothesis=hypothesis,
        created_at=created_at or datetime.now(timezone.utc).isoformat(),
    )


def build_research_run(
    research_run_id: str,
    experiment_id: str,
    dataset_snapshot_id: str,
    seed: Optional[int] = None,
    engine_version: str = ENGINE_VERSION,
    git_sha: Optional[str] = "auto",
    repo_dir: Optional[Union[str, Path]] = None,
    completed_at: Optional[str] = None,
) -> ResearchRun:
    """Construit un `ResearchRun`. `completed_at` auto-rempli (UTC) si non fourni.

    `dataset_snapshot_id` est **obligatoire** (voir invariant du module) : lève `ValueError` si
    absent/vide — un `ResearchRun` sans identité dataset ne serait pas un record reproductible.
    Un job qui n'a pas encore d'identité dataset exploitable ne doit tout simplement pas produire
    de `ResearchRun` (voir `job_store.write_research_run()`, best-effort : une telle tentative est
    silencieusement ignorée, elle ne fait jamais échouer le job).

    `git_sha="auto"` (défaut, AF-R-02) détecte le commit Git courant via
    `market_data.backtest_manifest._current_git_commit(repo_dir)` — passer explicitement `None`
    désactive la détection (tests hors dépôt, environnement sans Git). `seed` reste `None` si non
    fourni, jamais inventé. `engine_version` réutilise `market_data.backtest_manifest.
    ENGINE_VERSION` par défaut (voir invariants du module ci-dessus pour la justification des
    trois).
    """
    if not isinstance(dataset_snapshot_id, str) or not dataset_snapshot_id.strip():
        raise ValueError(
            "dataset_snapshot_id est obligatoire pour construire un ResearchRun — un ResearchRun "
            "sans identité dataset ne serait pas un record scientifique reproductible (voir "
            "AF-R-01 critère d'acceptation ; DOMAIN_MODEL.md ligne 163)."
        )
    resolved_git_sha = _current_git_commit(repo_dir) if git_sha == "auto" else git_sha
    return ResearchRun(
        research_run_id=validate_portable_identifier(research_run_id, "research_run_id"),
        experiment_id=validate_portable_identifier(experiment_id, "experiment_id"),
        dataset_snapshot_id=dataset_snapshot_id,
        git_sha=resolved_git_sha,
        seed=seed,
        engine_version=engine_version,
        completed_at=completed_at or datetime.now(timezone.utc).isoformat(),
    )


def save_experiment(path: Union[str, Path], experiment: Experiment) -> Path:
    """Écriture atomique de l'`Experiment`. Lève `FileExistsError` si déjà écrit (immuable)."""
    return save_atomic(path, asdict(experiment), "experiment")


def save_research_run(path: Union[str, Path], research_run: ResearchRun) -> Path:
    """Écriture atomique du `ResearchRun`. Lève `FileExistsError` si déjà écrit (immuable)."""
    return save_atomic(path, asdict(research_run), "research_run")


def load_experiment(path: Union[str, Path]) -> Optional[Experiment]:
    return load_tolerant(path, Experiment)


def load_research_run(path: Union[str, Path]) -> Optional[ResearchRun]:
    return load_tolerant(path, ResearchRun)
