"""
atomic_json_store.py — écriture atomique JSON + lecture tolérante, partagée (AF-R-03).

Extrait de `research_run.py` (motif lui-même mirroré de `market_data/backtest_manifest.py`) au
moment où une TROISIÈME implémentation quasi identique allait apparaître dans `dataset_split.py`
— Rule of Three, déjà signalée comme point de vigilance par les revues `/code-review` d'AF-R-01/02
("duplication de l'écriture atomique — pas encore 3 occurrences"). `market_data/backtest_manifest.py`
n'est délibérément PAS migré vers ce module : déjà committé/poussé (checkpoint DATA FOUNDATION),
hors scope de ce ticket non commité — voir `docs/roadmap/EPICS_AND_TICKETS.md`.

Motif : dataclasses `frozen`, écriture atomique (fichier temporaire + `os.replace()`), jamais
écrasées (`FileExistsError` explicite si le fichier existe déjà), lecture tolérante (`None` si
absent/illisible/invalide, jamais d'exception).

**Revue AF-R-03 (2026-08-15, `/code-review` — deux trouvailles corrigées)** :
- `validate_identifier()` — déplacée ici depuis `research_run.py` (où elle était `_validate_identifier`,
  privée) : `dataset_split.py` la réutilisait par un import cross-module d'un symbole privé, exactement
  le genre de duplication de plomberie que ce module existe pour éliminer. Désormais partagée
  explicitement, plus un `import` privé.
- `load_json_tolerant()` — extrait de `load_tolerant()` : `dataset_split.load_dataset_split_plan()`
  a des champs dataclass imbriqués (`SplitBoundary`) que `load_tolerant(path, cls)` ne peut pas
  reconstruire (`cls(**data)` ne rehydrate pas les sous-objets) ; sans cette extraction, il devait
  ré-implémenter tout le bloc lecture/`json.loads`/gestion d'erreurs de `load_tolerant()` pour n'en
  changer que la dernière étape (construction). `load_json_tolerant()` isole cette partie commune
  (fichier -> `dict` tolérant), réutilisée par `load_tolerant()` ET par tout chargeur à
  reconstruction personnalisée.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Optional, Union


def save_atomic(path: Union[str, Path], data: dict, kind: str) -> Path:
    """Écriture atomique commune : fichier temporaire + `os.replace()`, jamais d'écrasement.

    **Revue AF-R-03 (MCP Codex, 2026-08-15)** : le nom du fichier temporaire inclut un suffixe
    `uuid4` unique par appel — deux écritures concurrentes (processus séparés, ex. jobs lancés en
    subprocess) visant par erreur/collision la même `path` ne partagent plus le même fichier
    intermédiaire, évitant qu'elles se corrompent mutuellement pendant l'écriture. Ne résout pas
    entièrement le TOCTOU inhérent au contrôle `target.is_file()` ci-dessous (inchangé depuis
    AF-R-01/`backtest_manifest.py`) — mais élimine le pire mode de défaillance (contenu entrelacé/
    corrompu), pour un coût minimal, sans verrou de fichier ni framework de transaction."""
    target = Path(path)
    if target.is_file():
        raise FileExistsError(
            f"Un {kind} existe déjà à {target} — immuable, utilise un nouveau chemin/identifiant "
            "plutôt que d'écraser celui-ci."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    return target


def load_json_tolerant(path: Union[str, Path]) -> Optional[dict]:
    """Lecture tolérante d'un fichier JSON vers un `dict` brut (pas de reconstruction de classe) :
    fichier absent, illisible ou invalide -> `None`, jamais d'exception. Bloc partagé par
    `load_tolerant()` et par tout chargeur à reconstruction personnalisée (champs imbriqués)."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def load_tolerant(path: Union[str, Path], cls):
    """Lecture tolérante commune : fichier absent, illisible ou invalide -> None, jamais
    d'exception. Pour un `cls` à champs dataclass imbriqués, `cls(**data)` ne suffit pas (les
    sous-objets restent des `dict` bruts après `json.loads`) — écrire un chargeur dédié réutilisant
    `load_json_tolerant()` à la place (voir `dataset_split.load_dataset_split_plan()`)."""
    data = load_json_tolerant(path)
    if data is None:
        return None
    try:
        return cls(**data)
    except TypeError:
        return None


def filesystem_safe(value: str) -> str:
    """Transformation générique : tout caractère hors `[A-Za-z0-9_.-]` devient `_`. Couvre `:`
    mais aussi `*`/`?`/`<`/`>`/`|` (caractères invalides sous Windows qu'un identifiant validé par
    `validate_identifier()` — qui ne bloque que `/`, `\\`, `..`, vide — peut encore contenir).
    Ne remplace jamais l'identité réelle : celle-ci reste dans le contenu JSON, cette
    transformation ne sert qu'à nommer un fichier.

    **Revue globale Track R (2026-08-15)** : déplacée ici depuis `dataset_split.py` où elle
    n'était appliquée qu'à `research_run_id`/`split_plan_id`/`accessed_at` — `/code-review`
    Standards a trouvé le même gap non corrigé sur `experiment_id` (`job_store.py`) et sur un
    `event_id` fourni explicitement par l'appelant (`dataset_split.py`) : identifiants de la même
    classe, même risque, corrigé partout maintenant via cette fonction partagée."""
    return re.sub(r"[^A-Za-z0-9_.-]", "_", value)


def validate_identifier(value: str, field_name: str) -> str:
    """Un identifiant sert souvent directement à construire un chemin de fichier (ex.
    `experiments/<experiment_id>.json`, `dataset_splits/<slug>/...`) : refuse tout ce qui pourrait
    faire sortir l'écriture du répertoire prévu (séparateur de chemin, `..`) ou tout identifiant
    vide. Partagée entre `research_run.py` et `dataset_split.py` (déplacée ici depuis
    `research_run.py` en revue AF-R-03 — trouvée par MCP Codex sur AF-R-01 à l'origine, pas une
    hypothèse défensive gratuite)."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} ne peut pas être vide : {value!r}")
    if "/" in value or "\\" in value or ".." in value:
        raise ValueError(
            f"{field_name} contient un séparateur de chemin ou '..', interdit : {value!r}"
        )
    return value


def validate_portable_identifier(value: str, field_name: str) -> str:
    """**Revue globale Track R (MCP Codex, 2026-08-15)** : `filesystem_safe()` est une
    transformation à PERTE, non injective — `"exp:a"` et `"exp*a"` produisent tous deux `"exp_a"`.
    Pour un identifiant **choisi par l'appelant** qui devient la clé de stockage d'une structure
    immuable (`experiment_id`, `research_run_id`, `split_plan_id`, `event_id` fourni
    explicitement), c'est un vrai risque de collision d'identité — pas un simple problème de
    traversal. Ce validateur **rejette** (ne transforme jamais) tout caractère hors
    `[A-Za-z0-9_.-]`, en plus des règles de `validate_identifier()`. `filesystem_safe()` reste
    utile ailleurs pour des valeurs non-identitaires qui doivent légitimement contenir des
    caractères comme `:` (ex. `accessed_at`, un timestamp ISO-8601, jamais lui-même une clé de
    stockage — l'unicité vient de `event_id`, strictement validé séparément)."""
    validate_identifier(value, field_name)
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise ValueError(
            f"{field_name} ne peut contenir que des lettres, chiffres, '_', '.', '-' — "
            f"caractère interdit (risque de collision via filesystem_safe()) : {value!r}"
        )
    return value
