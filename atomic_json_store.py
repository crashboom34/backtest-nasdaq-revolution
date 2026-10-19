"""
atomic_json_store.py — écriture atomique JSON + lecture tolérante, partagée (AF-R-03).

Extrait de `research_run.py` (motif lui-même mirroré de `market_data/backtest_manifest.py`) au
moment où une TROISIÈME implémentation quasi identique allait apparaître dans `dataset_split.py`
— Rule of Three, déjà signalée comme point de vigilance par les revues `/code-review` d'AF-R-01/02
("duplication de l'écriture atomique — pas encore 3 occurrences"). `market_data/backtest_manifest.py`
n'est délibérément PAS migré vers ce module : déjà committé/poussé au moment d'AF-R-03 (checkpoint
DATA FOUNDATION), hors scope de ce ticket — voir `docs/roadmap/EPICS_AND_TICKETS.md`. (Ce module a
depuis lui-même été committé/poussé avec le reste de Track R, `90e3e29c4c994c4bb54e571240a4121d5d2b16ee`.)

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

import errno
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Union


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


def save_atomic_overwrite(path: Union[str, Path], data: dict, kind: str) -> Path:
    """Comme `save_atomic()`, mais AUTORISE l'écrasement d'un fichier déjà existant — réservée à
    un état **mutable** qui doit être réécrit à chaque transition (ex. état runtime de
    l'Autopilot, `scripts/autopilot/`, Bootstrap 2026-09-17), jamais à un artefact scientifique
    immuable (ceux-ci restent sur `save_atomic()`, dont le refus d'écrasement ne change jamais).
    `kind` n'est conservé que pour la symétrie de signature avec `save_atomic()` (utile aux
    messages d'erreur/logs appelants) — il ne peut jamais déclencher de `FileExistsError` ici.
    Même mécanisme atomique (fichier temporaire unique par `uuid4` + `os.replace()`) : une
    écriture interrompue ne laisse jamais le fichier cible partiellement écrit."""
    del kind  # jamais utilisé pour bloquer l'écrasement ici, contrairement à save_atomic()
    target = Path(path)
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


class ExclusiveCreationIncompleteError(OSError):
    """Levée UNIQUEMENT par `save_exclusive(..., durable=True)`, APRÈS une création exclusive réussie : le chemin
    existe (et reste consommé) mais son écriture, son flush, sa fermeture ou un fsync a échoué. Jamais confondue
    avec le refus initial d'`O_EXCL` (`FileExistsError`) : une erreur — même `FileExistsError` — survenue après la
    création est toujours rangée ici, avec l'erreur d'origine en `__cause__` et le chemin créé en `path`."""

    def __init__(self, message: str, path: Union[str, Path]):
        super().__init__(message)
        self.path = Path(path)


# Le fsync d'un RÉPERTOIRE n'existe que sous POSIX (ouvrir un répertoire échoue sous Windows) : sous Windows la
# durabilité de l'entrée de répertoire repose sur le journal NTFS et n'est pas démontrable depuis Python.
_DIRECTORY_FSYNC_SUPPORTED = os.name == "posix"


def _fsync_directory(directory: Union[str, Path]) -> None:
    descriptor = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _save_exclusive_durable(target: Path, data: dict, kind: str) -> Path:
    """Mode `durable=True` de `save_exclusive` (ADR 0025 Décision 22.8). Avant toute création : payload encodé en
    UTF-8 et, sous POSIX, sonde du fsync du répertoire parent — une erreur ici n'a rien créé. Puis création
    exclusive ; ensuite écriture, flush, fsync du fichier, fermeture et (POSIX) fsync du répertoire : toute
    erreur à partir de l'ouverture réussie devient `ExclusiveCreationIncompleteError`. Le fichier créé n'est
    JAMAIS supprimé. Ne garantit pas la survie à toute panne matérielle : seulement que le système a été prié de
    persister le fichier (et son entrée de répertoire sous POSIX) avant de rendre la main. Une interruption
    (`KeyboardInterrupt`, autre `BaseException`) n'est PAS rangée en `ExclusiveCreationIncompleteError` : elle se
    propage telle quelle, le chemin créé restant consommé."""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except FileExistsError as error:
        # Le parent existe mais n'est pas un répertoire : AUCUNE tentative n'a eu lieu sur le chemin du Claim. Ce n'est
        # donc pas le refus d'`O_EXCL` et ne doit jamais être lu comme « déjà consommé » (FileExistsError réservée à
        # ce refus). Le mode historique garde, lui, son comportement d'origine.
        raise NotADirectoryError(
            f"Le parent de {target} existe mais n'est pas un répertoire : le {kind} n'a pas été créé."
        ) from error
    body = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if _DIRECTORY_FSYNC_SUPPORTED:
        _fsync_directory(target.parent)
    try:
        # O_BINARY (Windows) : écriture octet pour octet, sans traduction de fin de ligne.
        descriptor = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0))
    except FileExistsError:
        raise FileExistsError(
            f"Un {kind} existe déjà à {target} — création exclusive refusée (une écriture "
            "concurrente a gagné la course, ou ce chemin a déjà été utilisé)."
        )
    try:
        try:
            handle = os.fdopen(descriptor, "wb")
        except BaseException:  # y compris une interruption : le descripteur ne fuit jamais ; l'erreur d'origine est relevée
            try:
                os.close(descriptor)
            except OSError:  # `io.open` a pu le fermer lui-même : un EBADF ne doit jamais masquer l'erreur d'origine
                pass
            raise
        with handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        if _DIRECTORY_FSYNC_SUPPORTED:
            _fsync_directory(target.parent)
    except Exception as error:
        raise ExclusiveCreationIncompleteError(
            f"Le {kind} a été créé à {target} (chemin consommé) mais son écriture durable est incomplète : {error}",
            target,
        ) from error
    return target


def save_exclusive(path: Union[str, Path], data: dict, kind: str, *, durable: bool = False) -> Path:
    """Création EXCLUSIVE atomique au niveau du système de fichiers — garantit l'exclusivité
    ENTRE PROCESSUS, contrairement à `save_atomic()` : celle-ci documente elle-même ne "pas
    résoudre entièrement le TOCTOU inhérent au contrôle `target.is_file()`" (contrôle et écriture
    restent deux opérations séparées). Réservée à un artefact où plusieurs processus concurrents
    doivent produire un unique gagnant déterministe (ex. `GateVPreRegistration` keyée par
    `scope_key`, futur `FinalHoldoutAccessClaim`, ADR 0025 Décision 9).

    Primitif retenu : `os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` — appel système
    indivisible unique sur l'entrée de répertoire, portable Windows (`CreateFileW(CREATE_NEW)`,
    garanti au niveau pilote NTFS) et POSIX (`open(2)` natif `O_EXCL`, garanti par le noyau).
    Écrit directement dans le descripteur ouvert en exclusivité — PAS de fichier temporaire
    intermédiaire + `os.replace()` comme `save_atomic()` : ce motif réintroduirait exactement la
    même fenêtre TOCTOU au moment du `replace()` (qui écrase inconditionnellement, sans jamais
    lever `FileExistsError`).

    **Matrice de crash** (même philosophie conservatrice que ADR 0025 Décision 9/11) :
    - crash AVANT l'appel `os.open()` : sûr, rien n'est créé, nouvelle tentative complète possible.
    - crash APRÈS acquisition (fichier créé) mais AVANT écriture complète : le chemin reste
      définitivement consommé (fichier présent, potentiellement tronqué/invalide) — AUCUN retry
      automatique. Le chargeur strict de l'appelant doit détecter tout contenu tronqué/invalide et
      échouer fermé, jamais l'accepter silencieusement comme valide.
    - crash APRÈS écriture complète : artefact valide, normal.
    - second processus concurrent : reçoit `FileExistsError` de façon synchrone, avant tout accès
      au contenu du premier — jamais d'inspection du détenteur existant, jamais de retry.

    **`durable` (ADR 0025 Décision 22.8, Slice E2)** — `False` (défaut) : comportement historique strictement
    inchangé (mêmes octets, mêmes exceptions, aucun fsync) pour tous les appelants existants. `True` : voir
    `_save_exclusive_durable` — flush et fsync du fichier, fsync du répertoire parent sous POSIX, toute erreur
    postérieure à la création = `ExclusiveCreationIncompleteError` (le chemin reste consommé). Limites :
    Windows ne permet pas le fsync de répertoire depuis Python (journal NTFS), un volume bloc OCI n'est pas
    qualifié, NFS/SMB/object-store ne sont pas supportés, et aucun fsync ne garantit la survie à toute panne."""
    target = Path(path)
    if durable:
        return _save_exclusive_durable(target, data, kind)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise FileExistsError(
            f"Un {kind} existe déjà à {target} — création exclusive refusée (une écriture "
            "concurrente a gagné la course, ou ce chemin a déjà été utilisé)."
        )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
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


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# AF-V-07 Slice E3-C — publication atomique et durable PAR LIEN (`tmp + fsync + os.link + fsync`)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Contrat normatif : ADR 0025 Décision 23, 23.10 (protocole, matrice de crash, `PublishedUnconfirmed`), 23.13 (événement canonique), 23.2 (profils de
# durabilité), 23.22 / 23.23 (primitive additive d'`atomic_json_store.py`), 23.29.1 et 23.29.4 (déclarations et attestations, temporaires
# `.exposure.tmp.<32 hex>`, JSON normatif). Section ADDITIVE : `save_atomic`, `save_atomic_overwrite`, `save_exclusive` (avec ou sans `durable=True`) et
# `ExclusiveCreationIncompleteError` sont inchangés (un test fige le SHA-256 du TEXTE SOURCE de chacune, relevé sur le commit 71095d0). Seuls les imports ont été complétés.
#
# CONTRAT D'API (les tests en dérivent). Ce qui vient de l'ADR : l'ordre du protocole 23.10, les deux états, les profils 23.2, les noms de temporaires
# 23.29.1, le JSON normatif 23.29.4, `FileExistsError` = slot occupé 23.13. Tout le reste est un choix d'implémentation PROPOSÉ, absent de l'ADR (AI_HANDOFF.md,
# section E3-C) : formes d'`uuid` du registre (uuid4 canonique), 3 essais de nom de temporaire, vocabulaire `UnconfirmedReason` et règle `st_nlink`, vérification
# des octets après le lien, résolution d'une erreur de `link` ambiguë par observation du slot, refus des noms Windows ambigus, refus de macOS pour `POSIX_DIR_FSYNC`,
# `fsync` du fichier du slot à la re-confirmation, `publication_id` (identifie l'APPEL : non persisté, non authentifié, jamais corrélé à la publication d'origine).
#   publish_bytes_by_link(destination, content, *, durability, naming, kind, precheck) -> LinkPublication
#   publish_json_by_link(destination, record, *, durability, naming, kind, precheck)  -> LinkPublication     (JSON normatif, `serialize_normative_json`)
#   confirm_published_slot(destination, *, expected_sha256, durability, expected_identity) -> LinkPublication  (re-confirmation : fsync SEUL, jamais de republication)
#   directory_read_barrier(directory, *, durability) -> None                                                   (barrière de lecture, 23.10 étape 1)
#
#   Succès : un `LinkPublication` d'état `PUBLISHED_DURABLE`. Il n'est JAMAIS renvoyé pour un lien non confirmé. Sous `SIMULATED_DURABLE`, `PUBLISHED_DURABLE`
#   n'a AUCUNE valeur de preuve de durabilité réelle (23.2) : `real_durability_demonstrated` est alors faux. Même sous `POSIX_DIR_FSYNC`, il dit seulement que le
#   `fsync` du répertoire a réussi sur un hôte POSIX non macOS : la qualification du système de fichiers (local, ni NFS/SMB, ni matériel qui ment sur `fsync`)
#   et de la plateforme (Linux/OCI, 23.2 et 23.9) n'est PAS vérifiée ici ; elle relève de l'admission REAL. Les chemins système POSIX (`O_DIRECTORY`,
#   `O_NOFOLLOW`, `fsync` d'un vrai descripteur de répertoire, `follow_symlinks=False`) ne sont exécutés que par les tests `posix_only`, jamais sous Windows.
#   LIMITES CONNUES : les opérations sont faites PAR CHEMIN (création, écriture, `link`, `lstat`, `unlink` du temporaire), seul le `fsync` utilise le descripteur
#   tenu. Un parent remplacé par un lien PENDANT `precheck` voit le temporaire créé, écrit et synchronisé À TRAVERS ce lien avant d'être détecté puis supprimé ; une
#   fenêtre TOCTOU subsiste aussi entre le dernier contrôle d'identité et le `link`. Les contrôles d'identité avant, juste après le lien et après la barrière la
#   DÉTECTENT (`PARENT_CHANGED`, `SLOT_IDENTITY_CHANGED`) mais ne l'excluent pas. Le durcissement `dir_fd` (`os.open/link/lstat/unlink(..., dir_fd=...)`, tous dans
#   `os.supports_dir_fd` sous Linux) est PROPOSÉ, NON implémenté : il touche l'UNIQUE chemin REAL et ne peut pas être exécuté sans Linux. Seul le parent FINAL est
#   contrôlé (pas ses ancêtres). Le nettoyage du temporaire (`lstat` puis `unlink` par chemin) a la même fenêtre ; l'inode d'un temporaire fermé peut être recyclé
#   (ext4/xfs) : garder le descripteur ouvert jusqu'au nettoyage est PROPOSÉ, non implémenté. Aucune permission restrictive n'est appliquée (23.24 ouvert).
#   Sur tmpfs, `fsync` de répertoire ne fait RIEN et renvoie 0 : `real_durability_demonstrated` y est vrai sans rien prouver (les tests sur un `tmp_path` tmpfs ne
#   prouvent aucune durabilité) ; l'admission REAL doit lister les systèmes de fichiers qualifiés. Hypothèse non exécutée : `fsync` sur un descripteur `O_RDONLY`
#   (répertoire, fichier du slot) est supporté par Linux. Un `PublishedUnconfirmedError` `DIRECTORY_FSYNC_FAILED` n'est PAS récupérable automatiquement de façon
#   fiable (erreur d'écriture déjà rapportée à un autre descripteur) : décision humaine ou remontage, pas une boucle de re-confirmation.
#   ORDRE : 23.10 étape 1 dit « lire la chaîne PUIS barrière de lecture » ; ici la barrière précède `precheck`. Un appelant qui lit la chaîne dans `precheck`
#   obtient barrière-puis-lecture : il doit lire AVANT l'appel et rappeler `directory_read_barrier` si l'ordre ADR est exigé. Après un lien, seules les exceptions
#   `OSError` sont converties en échecs typés ; une interruption ou un `MemoryError` se propage tel quel (temporaire conservé, slot binding).
#   PRÉCONDITIONS d'un écrivain qui consomme un slot DENSE et IRRÉPARABLE (B6, E3-D, E3-G ; AI_HANDOFF.md §61) : prouver AVANT la publication que SON lecteur
#   relira ces octets, au niveau de la LIGNÉE et pas seulement du fichier (une preuve par fichier laisse passer une chaîne cassée : test d'intégration). La preuve
#   passée à `precheck` doit porter sur LES MÊMES OCTETS que ceux publiés (la primitive ne le vérifie pas : `precheck` est une fermeture sans argument), avec les
#   MÊMES arguments que la lecture réelle (`campaign_id`, `pinned_a0_hashes`, `admitted_attestation`) ; elle suppose UN SEUL écrivain par campagne et laisse une
#   fenêtre entre la preuve et le `link` ; une copie de répertoire doit refuser les liens et conserver les métadonnées que le lecteur observe.
#   Échecs (exceptions `LinkPublicationError`, qui n'est PAS une `OSError` : un `except OSError` ne doit jamais attraper `PublishedUnconfirmedError` ; seul
#   `SlotOccupiedError` est une `FileExistsError`, 23.13 ; attributs de classe `replay_safe` et `slot_is_binding`) :
#     PlatformNotQualifiedError   profil exigé indisponible sur cette plateforme : rien n'a été créé.
#     PublicationNotStartedError  échec AVANT la création du lien (étape `stage`) : rien n'est publié, le slot n'a pas changé, rejeu possible.
#     SlotOccupiedError           `FileExistsError` au `link` : le slot est occupé ; jamais écrasé ; la relecture appartient à l'appelant.
#     PublishedUnconfirmedError   le lien EXISTE mais sa durabilité n'est pas confirmée (fsync en échec, ou vérification post-lien en défaut) :
#                                 `PublishedUnconfirmed` (23.10) ; le slot est BINDING pour tous les écrivains ; jamais supprimé. EXCEPTION `reason ==
#                                 LINK_OUTCOME_UNKNOWN` : `link` a échoué d'une façon ambiguë (EIO, ESTALE, ETIMEDOUT, EINTR, ECONNRESET) et le slot est
#                                 inobservable : le lien existe PEUT-ÊTRE, jamais une certitude ; même traitement (binding, temporaire conservé) ;
#                                 `confirm_published_slot` lèvera `SlotAbsentError` si rien n'a été publié (rejeu alors permis sous les règles d'unicité).
#     SlotAbsentError / SlotContentMismatchError   (re-confirmation seulement) le slot a disparu, ou son contenu n'est pas celui attendu.
#
#   E3-C n'implémente AUCUNE règle métier du registre, des déclarations ni de l'événement : ni unicité par campagne, ni recouvrement, ni nouvelle tentative
#   (`REGISTRY_CONTENTION`), ni politique propre à la `CONSUMPTION` (aucune re-confirmation après redémarrage : orchestrateur / registre). Il fournit les
#   informations vérifiables qui permettent à l'appelant de bâtir cette politique : identité du fichier (`FileIdentity` ; `st_dev`/`st_ino` ne valent que pour la
#   session et le montage courants, pas après un redémarrage ou une restauration), opération `PUBLISHED` / `RECONFIRMED`, `writer_pid`. Elles ne PROUVENT PAS que
#   la re-confirmation a lieu dans l'appel qui a publié (`publication_id` n'est pas persisté) : faire respecter « même appel » (23.10) incombe à l'orchestrateur,
#   qui doit conserver l'exception ou le résultat de l'appel. Le mode de défaillance « lien dur étranger vers le slot » reste `PUBLISHED_UNCONFIRMED` sans
#   récupération automatique : décision humaine.


class DurabilityProfile(str, Enum):
    """Profil de durabilité (ADR 0025 23.2). `POSIX_DIR_FSYNC` : `fsync` du fichier puis du répertoire parent, seul profil de `REAL`, refusé hors POSIX.
    `SIMULATED_DURABLE` : la même séquence s'exécute, la barrière de répertoire est SIMULÉE (fautes injectables par les tests) : aucune preuve de durabilité."""

    POSIX_DIR_FSYNC = "POSIX_DIR_FSYNC"
    SIMULATED_DURABLE = "SIMULATED_DURABLE"


class PublicationState(str, Enum):
    """États de 23.10 : `PUBLISHED_DURABLE` (`fsync` du répertoire réussi) ; `PUBLISHED_UNCONFIRMED` (lien fait, `fsync` absent ou en échec)."""

    PUBLISHED_DURABLE = "PUBLISHED_DURABLE"
    PUBLISHED_UNCONFIRMED = "PUBLISHED_UNCONFIRMED"


class PublicationOperation(str, Enum):
    PUBLISHED = "PUBLISHED"        # le lien a été créé par CET appel
    RECONFIRMED = "RECONFIRMED"    # seul un nouveau `fsync` du répertoire a été fait (aucune écriture, aucun lien)


class PublicationStage(str, Enum):
    """Étape où un échec AVANT le lien s'est produit (`PublicationNotStartedError.stage`)."""

    PREFLIGHT = "PREFLIGHT"
    BARRIER = "BARRIER"
    PRECHECK = "PRECHECK"        # RÉSERVÉ, jamais levé : l'exception d'un `precheck` se propage TELLE QUELLE (aucun fichier n'a été créé)
    TEMP_CREATE = "TEMP_CREATE"
    TEMP_WRITE = "TEMP_WRITE"
    TEMP_FSYNC = "TEMP_FSYNC"
    TEMP_CLOSE = "TEMP_CLOSE"
    LINK = "LINK"


class TempNaming(str, Enum):
    """Nommages FERMÉS des temporaires : aucun nom arbitraire (les tables fermées des scanners ne tolèrent un orphelin que pour `EXPOSURE` et seulement sous `exposure/` ; `REGISTRY` n'est toléré NULLE PART : voir
    AI_HANDOFF.md §60.7)."""

    EXPOSURE = "EXPOSURE"    # `.exposure.tmp.<32 hexadécimaux>` (23.29.1) : déclarations et attestations
    REGISTRY = "REGISTRY"    # `.registry.tmp.<uuid>` (23.10 étape 7) : registre ; `<uuid>` = forme canonique d'`uuid4` (PROPOSÉ : l'ADR ne la fixe pas)


class TempDisposition(str, Enum):
    NOT_CREATED = "NOT_CREATED"
    REMOVED = "REMOVED"                                  # le temporaire de CET appel a été supprimé (identité vérifiée)
    ALREADY_ABSENT = "ALREADY_ABSENT"
    REMOVAL_FAILED = "REMOVAL_FAILED"                    # orphelin inoffensif laissé (23.10 étape 7)
    IDENTITY_MISMATCH_KEPT = "IDENTITY_MISMATCH_KEPT"    # le nom désigne un autre fichier que le nôtre : jamais supprimé
    KEPT_UNCONFIRMED = "KEPT_UNCONFIRMED"                # publication non confirmée : temporaire conservé (aucune réparation destructive)


class UnconfirmedReason(str, Enum):
    """Vocabulaire FERMÉ des causes de `PublishedUnconfirmed` (`PublishedUnconfirmedError.reason`) : le lien existe mais la durabilité n'est pas démontrée."""

    DIRECTORY_FSYNC_FAILED = "DIRECTORY_FSYNC_FAILED"    # le `fsync` du répertoire (ou sa barrière simulée) a échoué après le lien
    FILE_FSYNC_FAILED = "FILE_FSYNC_FAILED"              # re-confirmation seulement : le `fsync` du fichier du slot (profil POSIX) a échoué
    SLOT_MISSING = "SLOT_MISSING"                        # le slot n'est plus observable juste après le lien
    SLOT_NOT_REGULAR = "SLOT_NOT_REGULAR"                # le slot n'est pas (ou plus) un fichier régulier
    SLOT_IDENTITY_CHANGED = "SLOT_IDENTITY_CHANGED"      # le slot désigne un autre fichier que celui de cet appel
    LINK_COUNT_ANOMALY = "LINK_COUNT_ANOMALY"            # `st_nlink != 2` : un lien dur étranger existe (ou un nom a disparu)
    CONTENT_CHANGED = "CONTENT_CHANGED"                  # les octets du slot ne sont pas ceux publiés
    SLOT_UNREADABLE = "SLOT_UNREADABLE"                  # le slot n'a pas pu être relu (droits, descripteurs, verrou) : vérification impossible
    LINK_OUTCOME_UNKNOWN = "LINK_OUTCOME_UNKNOWN"        # `link` a échoué d'une façon qui peut SUIVRE un lien abouti ET le slot est inobservable : le lien existe PEUT-ÊTRE
                                                         # (jamais une certitude) ; `confirm_published_slot` dira `SlotAbsentError` si rien n'a été publié
    PARENT_CHANGED = "PARENT_CHANGED"                    # le répertoire parent n'est plus celui tenu par l'ancre


EXPOSURE_TEMP_NAME_PATTERN = r"\.exposure\.tmp\.[0-9a-f]{32}"
# PROPOSÉ (l'ADR 23.10 dit seulement `.registry.tmp.<uuid>`) : uuid4 canonique, minuscules, avec tirets.
REGISTRY_TEMP_NAME_PATTERN =r"\.registry\.tmp\.[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
_EXPOSURE_TEMP_RE = re.compile(EXPOSURE_TEMP_NAME_PATTERN)
_REGISTRY_TEMP_RE = re.compile(REGISTRY_TEMP_NAME_PATTERN)


def is_publication_temp_name(name: str) -> Optional[TempNaming]:
    """Forme de temporaire de publication reconnue (`None` si le nom n'est exactement aucune des deux formes fermées)."""
    if _EXPOSURE_TEMP_RE.fullmatch(name):
        return TempNaming.EXPOSURE
    if _REGISTRY_TEMP_RE.fullmatch(name):
        return TempNaming.REGISTRY
    return None


class NormativeJsonError(ValueError):
    """La donnée n'a pas de représentation conforme au JSON normatif (23.29.4) : refusée AVANT toute création."""


def _check_normative_value(value, where: str) -> None:
    kind = type(value)
    if value is None or kind is bool or kind is int or kind is str:
        if kind is str:
            try:
                value.encode("utf-8")
            except UnicodeEncodeError:
                raise NormativeJsonError(f"{where} : texte non encodable en UTF-8 (substitut isolé).") from None
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise NormativeJsonError(f"{where} : clé non textuelle {key!r}.")
            _check_normative_value(key, f"{where}.<clé>")
            _check_normative_value(item, f"{where}.{key}")
        return
    if kind is list:
        for index, item in enumerate(value):
            _check_normative_value(item, f"{where}[{index}]")
        return
    raise NormativeJsonError(f"{where} : type {kind.__name__} hors du JSON normatif (aucun flottant, tuple, ensemble ni octets).")


def serialize_normative_json(record) -> bytes:
    """Octets NORMATIFS (23.29.4) : `json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\\n"`, UTF-8, fins de ligne LF.
    Racine = objet ; seuls `dict` (clés texte), `list`, `str`, `int`, `bool` et `None` sont admis : AUCUN flottant (23.29.4 « sans flottant »). Refusée AVANT toute
    création : `NormativeJsonError` (y compris imbrication trop profonde ou structure cyclique). Distinct du hash sémantique canonique compact (Décision 20.3) et
    des hashs de contenu, que l'appelant calcule. AUCUNE borne de profondeur ni de taille ici (les plafonds du lecteur B6/B5 sont provisoires, 23.31.5) : un
    appelant qui publie un slot dense et irréparable doit prouver, AVANT la publication (par exemple dans `precheck`), que son lecteur relira ces octets."""
    if type(record) is not dict:
        raise NormativeJsonError("la racine doit être un objet JSON (dict).")
    try:
        _check_normative_value(record, "$")
        text = json.dumps(record, sort_keys=True, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        return text.encode("utf-8")
    except RecursionError as error:
        raise NormativeJsonError("imbrication trop profonde ou structure cyclique.") from error
    except NormativeJsonError:
        raise
    except (ValueError, TypeError, UnicodeEncodeError) as error:
        raise NormativeJsonError(f"représentation impossible : {error}") from error


@dataclass(frozen=True)
class FileIdentity:
    """Identité vérifiable d'un fichier publié : périphérique et inode (`os.stat`), taille et SHA-256 des octets."""

    device: int
    inode: int
    size: int
    sha256: str


def _restore_publication_error(cls, args: tuple, state: dict):
    obj = cls.__new__(cls, *args)
    if isinstance(obj, OSError):
        OSError.__init__(obj, *args)           # restaure `errno` et `strerror` (SlotOccupiedError est aussi une FileExistsError)
    else:
        Exception.__init__(obj, *args)
    obj.__dict__.update(state)
    return obj


class LinkPublicationError(Exception):
    """Base de tous les échecs de la publication par lien. `destination` : chemin visé ; `stage` : étape (échecs avant le lien).

    Volontairement PAS une `OSError` (seul `SlotOccupiedError` l'est, via `FileExistsError`, 23.13) : un `except OSError: republier` ne doit jamais attraper un
    `PublishedUnconfirmedError` (« étape suivante interdite », 23.10). Deux attributs de classe disent comment réagir : `replay_safe` (rien n'est publié, un rejeu
    avec un nouveau nom de temporaire est permis) et `slot_is_binding` (le slot est occupé et le reste : jamais supprimé ni republié)."""

    replay_safe = False
    slot_is_binding = False

    def __init__(self, message: str, destination: Union[str, Path], *, stage: Optional[PublicationStage] = None) -> None:
        Exception.__init__(self, message)
        self.destination = Path(destination)
        self.stage = stage

    def __reduce__(self):
        # Les constructeurs exigent des arguments nommés : sans ceci, `pickle` / `copy` échouent (échec perdu à la frontière d'un processus enfant).
        return _restore_publication_error, (type(self), self.args, dict(self.__dict__))


class PlatformNotQualifiedError(LinkPublicationError):
    """Le profil de durabilité exigé n'est pas disponible sur cette plateforme (ex. `POSIX_DIR_FSYNC` sous Windows) : RIEN n'a été créé."""


class PublicationNotStartedError(LinkPublicationError):
    """Échec AVANT la création du lien : rien n'est publié, le slot n'a pas changé, un rejeu avec un nouveau nom de temporaire est permis (23.10). `replay_safe`
    dit seulement que REJOUER ne peut rien corrompre, PAS que rejouer réussira : EPERM, EXDEV, EACCES, ENOSPC sont déterministes (`filesystem_not_qualified`,
    errno de `__cause__`) ; une boucle de rejeu naïve tournerait indéfiniment.
    `temp_disposition` : sort du temporaire de cet appel ; `filesystem_not_qualified` : le système de fichiers refuse les liens durs."""

    replay_safe = True

    def __init__(self, message: str, destination: Union[str, Path], *, stage: PublicationStage,
                 temp_disposition: TempDisposition = TempDisposition.NOT_CREATED, temp_path: Optional[Path] = None,
                 filesystem_not_qualified: bool = False) -> None:
        super().__init__(message, destination, stage=stage)
        self.temp_disposition = temp_disposition
        self.temp_path = temp_path
        self.filesystem_not_qualified = filesystem_not_qualified


class SlotOccupiedError(LinkPublicationError, FileExistsError):
    """`FileExistsError` au `link` : le slot est occupé (jamais écrasé). Ce n'est NI un succès NI une idempotence : la relecture et la comparaison du contenu
    existant relèvent de l'appelant ; pour le registre, un nouvel essai exige de REVENIR À L'ÉTAPE 1 et de rejouer TOUTES les vérifications (23.10 étape 5,
    23.27.4), pas de publier directement dans le slot suivant (hors E3-C). OCCUPÉ ne veut PAS dire DURABLE : un slot laissé par un écrivain mort peut être
    `PUBLISHED_UNCONFIRMED` ; après relecture stricte et égalité du contenu, `confirm_published_slot` reste nécessaire avant de le tenir pour durable."""

    slot_is_binding = True

    def __init__(self, message: str, destination: Union[str, Path], *, temp_disposition: TempDisposition = TempDisposition.NOT_CREATED,
                 temp_path: Optional[Path] = None) -> None:
        FileExistsError.__init__(self, errno.EEXIST, message)
        self.destination = Path(destination)
        self.stage = PublicationStage.LINK
        self.temp_disposition = temp_disposition
        self.temp_path = temp_path


class PublishedUnconfirmedError(LinkPublicationError):
    """`PublishedUnconfirmed` (23.10) : le lien existe, sa durabilité n'est PAS confirmée. `publication` porte l'identité du fichier ; `slot_is_binding` est
    toujours vrai : les autres écrivains doivent traiter le slot comme occupé ; il n'est jamais supprimé ni republié. Pour `reason == LINK_OUTCOME_UNKNOWN`, le
    lien existe PEUT-ÊTRE seulement (`publication` décrit alors le fichier de CET appel, pas un slot constaté)."""

    slot_is_binding = True

    def __init__(self, message: str, destination: Union[str, Path], *, publication: "LinkPublication", reason: UnconfirmedReason) -> None:
        super().__init__(message, destination)
        self.publication = publication
        self.reason = reason


class SlotAbsentError(LinkPublicationError):
    """Re-confirmation : le slot n'existe pas (ou plus) : rien n'a été publié (23.10)."""


class SlotContentMismatchError(LinkPublicationError):
    """Re-confirmation : le slot existe mais ce n'est pas le fichier attendu (contenu ou identité) : jamais confirmé."""


@dataclass(frozen=True)
class LinkPublication:
    """Résultat vérifiable d'une publication ou d'une re-confirmation. `real_durability_demonstrated` n'est vrai que pour `PUBLISHED_DURABLE` obtenu avec
    `POSIX_DIR_FSYNC` (le `fsync` du répertoire a réussi) ; sous `SIMULATED_DURABLE`, il est faux et l'état n'a aucune valeur de preuve (23.2) : un consommateur
    REAL doit tester ce drapeau (ou le profil), JAMAIS `state` seul. Il ne qualifie ni le système de fichiers ni la plateforme. `publication_id` identifie
    l'APPEL (nouvel identifiant à chaque re-confirmation) : il n'est ni persisté, ni authentifié, ni corrélé à la publication d'origine."""

    destination: Path
    state: PublicationState
    durability_profile: DurabilityProfile
    operation: PublicationOperation
    identity: FileIdentity
    publication_id: str
    writer_pid: int
    temp_path: Optional[Path]
    temp_disposition: TempDisposition
    temp_cleanup_error: Optional[str] = None

    @property
    def real_durability_demonstrated(self) -> bool:
        return self.state is PublicationState.PUBLISHED_DURABLE and self.durability_profile is DurabilityProfile.POSIX_DIR_FSYNC


# ── Barrière de répertoire : ancre ───────────────────────────────────────────────────────────────────────────────────

_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _is_symlink_or_reparse_point(info) -> bool:
    """Lien symbolique, jonction ou point d'analyse : jamais suivi (la publication refuse un parent ainsi fait)."""
    return stat.S_ISLNK(info.st_mode) or bool((getattr(info, "st_file_attributes", 0) or 0) & _REPARSE_POINT_ATTRIBUTE)


def _simulated_directory_barrier(directory: Path) -> None:
    """Barrière de répertoire SIMULÉE du profil `SIMULATED_DURABLE` (23.2) : ne persiste RIEN et n'a aucune valeur de preuve. Point d'injection de faute."""
    return None


def _close_quietly(descriptor: int) -> None:
    """Ferme un descripteur en AVALANT l'`OSError` : un échec de fermeture ne doit jamais remplacer un résultat ni une exception en cours."""
    try:
        os.close(descriptor)
    except OSError:
        pass


def _open_posix_directory_descriptor(directory: Path) -> tuple:
    """POSIX uniquement : ouvre le répertoire SANS suivre de lien final (`O_NOFOLLOW`, `O_DIRECTORY`) et retourne `(descripteur, (st_dev, st_ino))`. Seul appel
    système réel du profil `POSIX_DIR_FSYNC` ; couvert par les tests `posix_only`, non exécutés sous Windows."""
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(str(directory), flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise NotADirectoryError(f"{directory} n'est pas un répertoire.")
    except BaseException:
        _close_quietly(descriptor)
        raise
    return descriptor, (info.st_dev, info.st_ino)


class _DirectoryAnchor:
    """Répertoire parent tenu pendant toute la publication : identité (`st_dev`, `st_ino`) relevée à l'ouverture et, pour `POSIX_DIR_FSYNC`, descripteur réel
    sur lequel le `fsync` est fait (jamais sur un chemin ré-résolu après coup)."""

    def __init__(self, directory: Path, identity: tuple, descriptor: Optional[int]) -> None:
        self.directory = directory
        self.identity = identity
        self.descriptor = descriptor

    def barrier(self) -> None:
        if self.descriptor is None:
            _simulated_directory_barrier(self.directory)
        else:
            os.fsync(self.descriptor)

    def close(self) -> None:
        if self.descriptor is not None:
            descriptor, self.descriptor = self.descriptor, None
            try:
                os.close(descriptor)
            except OSError:
                pass    # le `fsync` est déjà fait et le descripteur est libéré : une erreur de fermeture ne doit JAMAIS remplacer le résultat ni une exception en cours


def _require_member(value, enum_class, name: str):
    if type(value) is not enum_class:
        raise TypeError(f"{name} doit être un {enum_class.__name__} (aucune valeur par défaut, aucun texte libre).")
    return value


_WINDOWS_DEVICE_STEMS = frozenset({"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))})


def _split_destination(destination) -> tuple:
    """`(répertoire parent ABSOLU, nom)`. Refuse toute composante `..`, un nom vide, un nom que le scanner prendrait pour un temporaire (`.tmp` final ou
    `.tmp.`) et, sous Windows, les noms qui désignent un AUTRE fichier que celui écrit (point ou espace final, `:` de flux de données, noms de périphériques).
    Le parent est rendu absolu SANS résoudre de lien (le contrôle de lien du parent reste entier) : une re-confirmation depuis un autre répertoire courant
    désigne le même fichier."""
    path = Path(destination)
    if ".." in path.parts:
        raise ValueError(f"composante '..' interdite dans la destination : {destination!r}")
    name = path.name
    if not name or name in (".", ".."):
        raise ValueError(f"destination sans nom de fichier : {destination!r}")
    folded = name.casefold()
    if is_publication_temp_name(name) is not None or folded.endswith(".tmp") or ".tmp." in folded:
        raise ValueError(f"nom de destination réservé aux temporaires : {name!r}")
    for part in (str(path.parent), name):
        if "\0" in part:
            raise ValueError(f"caractère NUL interdit dans la destination : {destination!r}")
        try:
            os.fsencode(part)
        except UnicodeEncodeError:
            raise ValueError(f"destination non encodable par le système de fichiers : {destination!r}") from None
    if (len(name) if os.name == "nt" else len(os.fsencode(name))) > 255:    # NAME_MAX : 255 octets (POSIX) ou 255 unités UTF-16 (approximées par les caractères)
        raise ValueError(f"nom de destination trop long (limite du système de fichiers) : {name[:40]!r}…")
    if os.name == "nt":
        if any(char in name for char in '<>"|?*') or any(ord(char) < 32 for char in name):
            raise ValueError(f"caractère réservé sous Windows dans le nom de destination : {name!r}")
        if name != name.rstrip(" .") or ":" in name:
            raise ValueError(f"nom de destination ambigu sous Windows (point ou espace final, ou ':') : {name!r}")
        if name.split(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICE_STEMS:
            raise ValueError(f"nom de destination réservé à un périphérique Windows : {name!r}")
    return Path(os.path.abspath(path.parent)), name


def _posix_profile_available() -> bool:
    """`POSIX_DIR_FSYNC` est disponible : hôte POSIX (`_DIRECTORY_FSYNC_SUPPORTED`, historique) ET pas macOS, où `os.fsync` n'est pas un vidage complet
    (`F_FULLFSYNC` requis) : la durabilité n'y serait pas démontrée. La qualification du système de fichiers (local, ni NFS/SMB) n'est PAS vérifiée ici."""
    return _DIRECTORY_FSYNC_SUPPORTED and sys.platform != "darwin"


def _open_anchor(directory: Path, durability: DurabilityProfile, destination: Path) -> _DirectoryAnchor:
    try:
        info = os.lstat(directory)
    except OSError as error:
        raise PublicationNotStartedError(f"répertoire parent inobservable : {error}", destination, stage=PublicationStage.PREFLIGHT) from error
    if _is_symlink_or_reparse_point(info):
        raise PublicationNotStartedError(f"{directory} est un lien ou un point d'analyse : refusé.", destination, stage=PublicationStage.PREFLIGHT)
    if not stat.S_ISDIR(info.st_mode):
        raise PublicationNotStartedError(f"{directory} n'est pas un répertoire.", destination, stage=PublicationStage.PREFLIGHT)
    identity = (info.st_dev, info.st_ino)
    if durability is DurabilityProfile.SIMULATED_DURABLE:
        return _DirectoryAnchor(directory, identity, None)
    try:
        descriptor, opened_identity = _open_posix_directory_descriptor(directory)
    except OSError as error:
        raise PublicationNotStartedError(f"ouverture du répertoire impossible : {error}", destination, stage=PublicationStage.PREFLIGHT) from error
    if opened_identity != identity:
        _close_quietly(descriptor)
        raise PublicationNotStartedError(f"{directory} a changé pendant son ouverture.", destination, stage=PublicationStage.PREFLIGHT)
    return _DirectoryAnchor(directory, identity, descriptor)


def _new_temp_name(naming: TempNaming) -> str:
    if naming is TempNaming.EXPOSURE:
        return f".exposure.tmp.{uuid.uuid4().hex}"
    return f".registry.tmp.{uuid.uuid4()}"


def _remove_own_temp(temp_path: Path, identity: tuple) -> tuple:
    """Supprime UNIQUEMENT le temporaire de cet appel : le nom doit encore désigner le fichier créé (même `st_dev`, `st_ino`). Retourne `(sort, erreur)`."""
    try:
        info = os.lstat(temp_path)
    except FileNotFoundError:
        return TempDisposition.ALREADY_ABSENT, None
    except OSError as error:
        return TempDisposition.REMOVAL_FAILED, str(error)
    if (info.st_dev, info.st_ino) != identity:
        return TempDisposition.IDENTITY_MISMATCH_KEPT, None
    try:
        os.unlink(temp_path)
    except FileNotFoundError:
        return TempDisposition.ALREADY_ABSENT, None
    except OSError as error:
        return TempDisposition.REMOVAL_FAILED, str(error)
    return TempDisposition.REMOVED, None


_TEMP_CREATE_ATTEMPTS = 3
_UNSUPPORTED_LINK_ERRNOS = frozenset(getattr(errno, name) for name in ("EPERM", "EXDEV", "ENOTSUP", "EOPNOTSUPP", "ENOSYS") if hasattr(errno, name))
_UNSUPPORTED_LINK_WINERRORS = frozenset({1, 50})  # ERROR_INVALID_FUNCTION, ERROR_NOT_SUPPORTED


def _link_is_unsupported(error: OSError) -> bool:
    """Le refus du `link` indique-t-il un système de fichiers sans liens durs ? Classement CONSERVATEUR : EPERM est aussi levé par des politiques de sécurité,
    l'appelant doit traiter `filesystem_not_qualified` comme « non qualifié », jamais comme une preuve de défaut du disque."""
    return error.errno in _UNSUPPORTED_LINK_ERRNOS or getattr(error, "winerror", None) in _UNSUPPORTED_LINK_WINERRORS


def _run_barrier(anchor: _DirectoryAnchor, destination: Path) -> None:
    """Barrière de lecture (23.10 étape 1) : un échec est un refus AVANT toute création."""
    try:
        anchor.barrier()
    except OSError as error:
        raise PublicationNotStartedError(f"barrière de répertoire en échec : {error}", destination, stage=PublicationStage.BARRIER) from error


def directory_read_barrier(directory, *, durability: DurabilityProfile) -> None:
    """Barrière de lecture seule (23.10 étape 1) : `fsync` du répertoire (profil POSIX) ou barrière simulée, sans rien créer. Un répertoire absent ou lien
    est refusé (`PublicationNotStartedError`, étape PREFLIGHT), jamais créé."""
    _require_member(durability, DurabilityProfile, "durability")
    path = Path(directory)
    if ".." in path.parts:
        raise ValueError(f"composante '..' interdite dans le répertoire : {directory!r}")
    if durability is DurabilityProfile.POSIX_DIR_FSYNC and not _posix_profile_available():
        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", path)
    anchor = _open_anchor(path, durability, path)
    try:
        _run_barrier(anchor, path)
    finally:
        anchor.close()


def publish_bytes_by_link(destination, content: bytes, *, durability: DurabilityProfile, naming: TempNaming, kind: str = "artefact",
                          precheck: Optional[Callable[[], None]] = None) -> LinkPublication:
    """Publie `content` à `destination` par `tmp + fsync + os.link + fsync` (ADR 0025 23.10) : le slot final est COMPLET ou ABSENT, jamais tronqué, jamais écrasé (démontré pour la MORT du processus ; aucune coupure d'alimentation n'est simulée).
    Voir le contrat en tête de section. `precheck` : appel sans argument fait après la barrière et avant tout fichier temporaire (vérifications de
    prépublication de l'appelant, 23.10 étape 2) ; ce qu'il lève se propage tel quel, rien n'a été créé."""
    if type(content) is not bytes:
        raise TypeError("content doit être exactement de type bytes.")
    _require_member(durability, DurabilityProfile, "durability")
    _require_member(naming, TempNaming, "naming")
    directory, name = _split_destination(destination)
    target = directory / name
    if durability is DurabilityProfile.POSIX_DIR_FSYNC and not _posix_profile_available():
        raise PlatformNotQualifiedError(
            f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme : le {kind} n'a pas été créé.", target)
    anchor = _open_anchor(directory, durability, target)
    try:
        _run_barrier(anchor, target)
        if precheck is not None:
            precheck()
        return _publish_with_anchor(anchor, target, content, durability, naming)
    finally:
        anchor.close()


def _create_temp_file(anchor: _DirectoryAnchor, naming: TempNaming, target: Path) -> tuple:
    """Crée le temporaire (`O_CREAT | O_EXCL`) dans le répertoire du slot ; une collision de nom est rejouée avec un NOUVEAU nom, au plus
    `_TEMP_CREATE_ATTEMPTS` fois (jamais d'écrasement d'un fichier existant). Retourne `(chemin, descripteur)`."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_CLOEXEC", 0)
    last_collision: Optional[BaseException] = None
    for _ in range(_TEMP_CREATE_ATTEMPTS):
        temp_path = anchor.directory / _new_temp_name(naming)
        try:
            return temp_path, os.open(str(temp_path), flags, 0o666)
        except FileExistsError as error:
            last_collision = error
        except OSError as error:
            raise PublicationNotStartedError(f"création du temporaire impossible : {error}", target, stage=PublicationStage.TEMP_CREATE) from error
    raise PublicationNotStartedError(f"{_TEMP_CREATE_ATTEMPTS} noms de temporaire déjà pris : abandon.", target,
                                     stage=PublicationStage.TEMP_CREATE) from last_collision


def _stage_temp(anchor: _DirectoryAnchor, target: Path, content: bytes, naming: TempNaming) -> tuple:
    """Étapes 3 et 4 de 23.10 : temporaire complet dans le répertoire du slot, `fsync` du fichier, fermeture. Retourne `(chemin, (st_dev, st_ino))`. Tout échec
    ou interruption AVANT le lien ferme le descripteur et supprime le seul temporaire de cet appel ; une erreur système devient
    `PublicationNotStartedError` (étape précise), tout le reste (interruption, bogue) se propage tel quel."""
    temp_path, descriptor = _create_temp_file(anchor, naming, target)
    identity: Optional[tuple] = None
    stage = PublicationStage.TEMP_CREATE
    descriptor_open = True
    try:
        info = os.fstat(descriptor)
        identity = (info.st_dev, info.st_ino)
        stage = PublicationStage.TEMP_WRITE
        view, written = memoryview(content), 0
        while written < len(content):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError(errno.EIO, "écriture sans progression du temporaire")
            written += count
        stage = PublicationStage.TEMP_FSYNC
        os.fsync(descriptor)
        stage = PublicationStage.TEMP_CLOSE
        descriptor_open = False  # un `close` en échec libère tout de même le descripteur (POSIX et Windows) : jamais de double fermeture
        os.close(descriptor)
    except BaseException as error:
        if descriptor_open:
            try:
                os.close(descriptor)
            except OSError:
                pass
        disposition = TempDisposition.REMOVAL_FAILED if identity is None else _remove_own_temp(temp_path, identity)[0]
        if isinstance(error, OSError):
            raise PublicationNotStartedError(f"échec à l'étape {stage.value} : {error}", target, stage=stage, temp_disposition=disposition,
                                             temp_path=temp_path) from error
        raise
    return temp_path, identity


def _link_precondition_problem(anchor: _DirectoryAnchor, temp_path: Path, temp_identity: tuple) -> Optional[str]:
    """Dernier contrôle AVANT `os.link` : le répertoire parent est toujours celui tenu par l'ancre (ni remplacé, ni devenu lien) et le nom du temporaire désigne
    toujours le fichier créé. Contrôle par chemin : une fenêtre TOCTOU résiduelle subsiste entre ce contrôle et le `link` (voir le contrat)."""
    try:
        parent = os.lstat(anchor.directory)
    except OSError as error:
        return f"répertoire parent inobservable avant le lien : {error}"
    if _is_symlink_or_reparse_point(parent) or (parent.st_dev, parent.st_ino) != anchor.identity:
        return f"le répertoire {anchor.directory} n'est plus celui tenu par la publication (remplacé ou devenu lien)."
    try:
        temp = os.lstat(temp_path)
    except OSError as error:
        return f"temporaire inobservable avant le lien : {error}"
    if _is_symlink_or_reparse_point(temp) or (temp.st_dev, temp.st_ino) != temp_identity:
        return "le temporaire n'est plus le fichier créé par cet appel."
    return None


def _parent_unchanged(anchor: _DirectoryAnchor) -> bool:
    try:
        parent = os.lstat(anchor.directory)
    except OSError:
        return False
    return not _is_symlink_or_reparse_point(parent) and (parent.st_dev, parent.st_ino) == anchor.identity


def _post_link_problem(anchor: _DirectoryAnchor, target: Path, temp_identity: tuple, content: bytes) -> Optional[UnconfirmedReason]:
    """Vérification APRÈS `os.link` (le temporaire existe encore) : le parent est toujours l'ancre, le slot est un fichier régulier, c'est BIEN le fichier de
    cet appel (même `st_dev`/`st_ino` que le temporaire), il n'a que ses deux noms (`st_nlink == 2` : aucun lien dur étranger) et ses octets sont exacts.
    Toute anomalie interdit de déclarer `PUBLISHED_DURABLE` ; rien n'est supprimé ni réparé."""
    if not _parent_unchanged(anchor):
        return UnconfirmedReason.PARENT_CHANGED
    try:
        slot = os.lstat(target)
    except OSError:
        return UnconfirmedReason.SLOT_MISSING
    if _is_symlink_or_reparse_point(slot) or not stat.S_ISREG(slot.st_mode):
        return UnconfirmedReason.SLOT_NOT_REGULAR
    if (slot.st_dev, slot.st_ino) != temp_identity:
        return UnconfirmedReason.SLOT_IDENTITY_CHANGED
    if slot.st_nlink != 2:
        return UnconfirmedReason.LINK_COUNT_ANOMALY
    try:
        with open(target, "rb") as handle:
            observed = handle.read(len(content) + 1)
    except OSError:
        return UnconfirmedReason.SLOT_UNREADABLE
    return None if observed == content else UnconfirmedReason.CONTENT_CHANGED


_SLOT_OURS, _SLOT_OTHER_OR_ABSENT, _SLOT_UNOBSERVABLE = "OURS", "OTHER_OR_ABSENT", "UNOBSERVABLE"
_AMBIGUOUS_LINK_ERRNOS = frozenset(getattr(errno, name) for name in ("EIO", "ESTALE", "ETIMEDOUT", "EINTR", "ECONNRESET") if hasattr(errno, name))


def _observe_slot_after_link_error(target: Path, temp_identity: tuple) -> str:
    """Après une erreur du `link` : le slot est-il un fichier régulier portant l'inode du temporaire (le lien a abouti malgré l'erreur : `_SLOT_OURS`), absent
    ou un AUTRE fichier (`_SLOT_OTHER_OR_ABSENT`), ou INOBSERVABLE (`_SLOT_UNOBSERVABLE` : droits, EIO...) ? Seul `FileNotFoundError` prouve l'absence : une
    observation impossible n'est jamais traitée comme « absent » (le lien a peut-être abouti)."""
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        return _SLOT_OTHER_OR_ABSENT
    except OSError:
        return _SLOT_UNOBSERVABLE
    ours = not _is_symlink_or_reparse_point(info) and (info.st_dev, info.st_ino) == temp_identity
    return _SLOT_OURS if ours else _SLOT_OTHER_OR_ABSENT


def _unconfirmed_error(reason: UnconfirmedReason, message: str, target: Path, temp_path: Path, temp_identity: tuple, content: bytes,
                       durability: DurabilityProfile) -> PublishedUnconfirmedError:
    """`PublishedUnconfirmed` (23.10) : le lien a été créé, la durabilité n'est pas confirmée. L'identité rapportée est celle du fichier de CET appel (le
    temporaire) ; le temporaire est conservé (`KEPT_UNCONFIRMED`) et le slot reste binding. EXCEPTION : pour `LINK_OUTCOME_UNKNOWN`, le lien existe PEUT-ÊTRE
    (jamais une certitude) ; le message le dit."""
    publication = LinkPublication(
        destination=target, state=PublicationState.PUBLISHED_UNCONFIRMED, durability_profile=durability, operation=PublicationOperation.PUBLISHED,
        identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(content).hexdigest()),
        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=TempDisposition.KEPT_UNCONFIRMED)
    if reason is UnconfirmedReason.LINK_OUTCOME_UNKNOWN:
        suffix = (f"Le slot {target} est PEUT-ÊTRE publié (issue du lien inconnue) : traité comme binding, temporaire conservé, rien n'est supprimé ni republié ; "
                  f"`confirm_published_slot` lèvera `SlotAbsentError` si rien n'a été publié.")
    else:
        suffix = f"Le slot {target} est publié mais NON confirmé : binding, jamais supprimé ni republié."
    return PublishedUnconfirmedError(f"{message} {suffix}", target, publication=publication, reason=reason)


def _publish_with_anchor(anchor: _DirectoryAnchor, target: Path, content: bytes, durability: DurabilityProfile, naming: TempNaming) -> LinkPublication:
    temp_path, temp_identity = _stage_temp(anchor, target, content, naming)
    try:
        problem = _link_precondition_problem(anchor, temp_path, temp_identity)
    except BaseException:
        _remove_own_temp(temp_path, temp_identity)
        raise
    if problem is not None:
        disposition, _ = _remove_own_temp(temp_path, temp_identity)
        raise PublicationNotStartedError(problem, target, stage=PublicationStage.LINK, temp_disposition=disposition, temp_path=temp_path)
    # Le comportement de `link` sur une SOURCE qui est un lien symbolique dépend de la plateforme (Linux ne le suit pas, d'autres systèmes POSIX peuvent le
    # suivre) : là où `follow_symlinks=False` existe, on le demande explicitement. Sous Windows l'option n'existe pas : la vérification d'identité après le
    # lien (`_post_link_problem`) reste la seule défense.
    link_options = {"follow_symlinks": False} if os.link in os.supports_follow_symlinks else {}
    link_error: Optional[OSError] = None
    try:
        os.link(str(temp_path), str(target), **link_options)
    except OSError as error:
        link_error = error
    observed = _observe_slot_after_link_error(target, temp_identity) if link_error is not None else _SLOT_OURS
    if observed == _SLOT_UNOBSERVABLE and link_error.errno in _AMBIGUOUS_LINK_ERRNOS and not isinstance(link_error, FileExistsError):
        # Erreur du `link` qui peut SUIVRE un lien abouti (réponse perdue, `EIO`, `ESTALE`...) ET slot inobservable : le lien a peut-être abouti. Jamais « rien
        # n'est publié, rejeu permis » sur une hypothèse : temporaire conservé, slot binding, aucune suppression. Une erreur DÉTERMINISTE (nom invalide : `link` et
        # `lstat` échouent pareil) n'entre PAS ici : elle reste un refus rejouable.
        raise _unconfirmed_error(UnconfirmedReason.LINK_OUTCOME_UNKNOWN, f"erreur du lien ({link_error}) et slot inobservable.", target, temp_path,
                                 temp_identity, content, durability) from link_error
    if observed != _SLOT_OURS:
        # Aucun lien n'est ÉTABLI pour cet appel (slot absent ou AUTRE fichier ; erreur déterministe ; ou `EEXIST` sur un slot inobservable : le slot existe, il
        # est occupé, même si un `EEXIST` parasite pouvait en être le nôtre : il reste binding et n'est jamais touché). Seul le
        # temporaire de CET appel est supprimé.
        disposition, _ = _remove_own_temp(temp_path, temp_identity)
        if isinstance(link_error, FileExistsError):
            # Le slot est occupé : jamais écrasé, jamais « déjà publié ».
            raise SlotOccupiedError(f"Le slot {target} est déjà occupé : création par lien refusée (jamais écrasé ; relecture et comparaison = appelant).",
                                    target, temp_disposition=disposition, temp_path=temp_path) from link_error
        raise PublicationNotStartedError(f"lien refusé : {link_error}", target, stage=PublicationStage.LINK, temp_disposition=disposition,
                                         temp_path=temp_path, filesystem_not_qualified=_link_is_unsupported(link_error)) from link_error
    # Une erreur du `link` alors que le slot porte DÉJÀ l'inode du temporaire (`EIO`, `EEXIST` parasite après retransmission) : le lien a abouti, l'erreur est
    # un faux négatif ; on poursuit avec les vérifications et la barrière (jamais « rien n'est publié » sur une simple hypothèse).
    # À partir d'ici le lien EXISTE. Une interruption (BaseException non OSError) pendant `link` ou ensuite laisse un état INCONNU ou non confirmé : elle se
    # propage telle quelle, le temporaire est conservé, rien n'est deviné ni supprimé.
    anomaly = _post_link_problem(anchor, target, temp_identity, content)
    if anomaly is not None:
        raise _unconfirmed_error(anomaly, f"Vérification après le lien en défaut ({anomaly.value}).", target, temp_path, temp_identity, content, durability)
    try:
        anchor.barrier()
    except OSError as error:
        raise _unconfirmed_error(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f"fsync du répertoire en échec ({error}).", target, temp_path, temp_identity,
                                 content, durability) from error
    # Après la barrière, MÊME contrôle qu'avant : le slot et le parent peuvent avoir changé pendant le `fsync`. Jamais de `PUBLISHED_DURABLE` pour un fichier
    # qui n'est pas celui de cet appel.
    anomaly = _post_link_problem(anchor, target, temp_identity, content)
    if anomaly is not None:
        raise _unconfirmed_error(anomaly, f"Vérification après la barrière en défaut ({anomaly.value}).", target, temp_path, temp_identity, content, durability)
    disposition, cleanup_error = _remove_own_temp(temp_path, temp_identity)
    return LinkPublication(
        destination=target, state=PublicationState.PUBLISHED_DURABLE, durability_profile=durability, operation=PublicationOperation.PUBLISHED,
        identity=FileIdentity(temp_identity[0], temp_identity[1], len(content), hashlib.sha256(content).hexdigest()),
        publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=temp_path, temp_disposition=disposition, temp_cleanup_error=cleanup_error)


def publish_json_by_link(destination, record: dict, *, durability: DurabilityProfile, naming: TempNaming, kind: str = "artefact",
                         precheck: Optional[Callable[[], None]] = None) -> LinkPublication:
    """`publish_bytes_by_link` des octets du JSON NORMATIF (`serialize_normative_json`). Une donnée non conforme est refusée AVANT toute création
    (`NormativeJsonError`)."""
    return publish_bytes_by_link(destination, serialize_normative_json(record), durability=durability, naming=naming, kind=kind, precheck=precheck)


_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _fsync_slot_file(path: Path) -> None:
    """`fsync` du FICHIER du slot, ouvert en lecture seule sans suivre de lien final (profil POSIX uniquement ; point d'injection de faute). Un `fsync` de
    répertoire ne persiste pas les données du fichier : un slot qui n'a pas été écrit par cette primitive doit être synchronisé avant d'être déclaré durable."""
    descriptor = os.open(str(path), os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _sha256_and_size(path: Path) -> tuple:
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def confirm_published_slot(destination, *, expected_sha256: str, durability: DurabilityProfile,
                           expected_identity: Optional[FileIdentity] = None) -> LinkPublication:
    """Re-confirmation d'un slot DÉJÀ publié (23.10) : relit le slot, vérifie qu'il est exactement celui attendu (octets, et identité si fournie) puis refait la
    barrière de répertoire. Lecture seule : AUCUNE création, écriture, lien ni suppression (`re-confirmation != republication`). Retourne un
    `LinkPublication` d'opération `RECONFIRMED` et d'état `PUBLISHED_DURABLE`. Le slot reste intact dans tous les cas d'échec :
    `SlotAbsentError` (absent : jamais republié), `SlotContentMismatchError` (autre fichier ou autres octets : jamais confirmé),
    `PublishedUnconfirmedError` (barrière en échec ou anomalie : toujours binding). La POLITIQUE de re-confirmation (par exemple aucune après un
    redémarrage pour la `CONSUMPTION`) appartient à l'orchestrateur : cette fonction ne fournit que l'information vérifiable. `expected_identity` (périphérique
    et inode) ne vaut que pour la session et le montage courants. Sous `POSIX_DIR_FSYNC`, le FICHIER du slot est aussi synchronisé avant le répertoire (un slot
    non écrit par cette primitive pourrait n'être qu'en cache). Un seul lien dur étranger est indiscernable de l'orphelin de publication conservé (2 noms)."""
    _require_member(durability, DurabilityProfile, "durability")
    if type(expected_sha256) is not str or not _SHA256_HEX.fullmatch(expected_sha256):
        raise ValueError("expected_sha256 doit être un SHA-256 hexadécimal minuscule de 64 caractères.")
    if expected_identity is not None and type(expected_identity) is not FileIdentity:
        raise TypeError("expected_identity doit être un FileIdentity ou None.")
    directory, name = _split_destination(destination)
    target = directory / name
    if durability is DurabilityProfile.POSIX_DIR_FSYNC and not _posix_profile_available():
        raise PlatformNotQualifiedError(f"Le profil {durability.value} exige un fsync de répertoire, indisponible sur cette plateforme.", target)
    anchor = _open_anchor(directory, durability, target)
    try:
        try:
            slot = os.lstat(target)
        except FileNotFoundError as error:
            raise SlotAbsentError(f"Le slot {target} est absent : rien à confirmer, rien republié.", target) from error
        except OSError as error:
            raise PublicationNotStartedError(f"slot inobservable : {error}", target, stage=PublicationStage.PREFLIGHT) from error
        if _is_symlink_or_reparse_point(slot) or not stat.S_ISREG(slot.st_mode):
            raise SlotContentMismatchError(f"Le slot {target} n'est pas un fichier régulier.", target)
        try:
            observed_sha256, observed_size = _sha256_and_size(target)
        except OSError as error:
            raise PublicationNotStartedError(f"slot illisible : {error}", target, stage=PublicationStage.PREFLIGHT) from error
        identity = FileIdentity(slot.st_dev, slot.st_ino, observed_size, observed_sha256)
        if observed_sha256 != expected_sha256:
            raise SlotContentMismatchError(f"Le contenu du slot {target} n'est pas celui attendu.", target)
        if expected_identity is not None and expected_identity != identity:
            raise SlotContentMismatchError(f"L'identité du slot {target} n'est pas celle attendue.", target)

        def unconfirmed(reason: UnconfirmedReason, message: str) -> PublishedUnconfirmedError:
            publication = LinkPublication(
                destination=target, state=PublicationState.PUBLISHED_UNCONFIRMED, durability_profile=durability, operation=PublicationOperation.RECONFIRMED,
                identity=identity, publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)
            return PublishedUnconfirmedError(f"{message} Le slot {target} reste publié mais NON confirmé : binding, jamais supprimé ni republié.", target,
                                             publication=publication, reason=reason)

        if slot.st_nlink > 2:    # 1 nom (nettoyé) ou 2 noms (orphelin de publication conservé) sont normaux ; davantage = lien dur étranger
            raise unconfirmed(UnconfirmedReason.LINK_COUNT_ANOMALY, f"Le slot a {slot.st_nlink} noms.")
        if durability is DurabilityProfile.POSIX_DIR_FSYNC:
            try:
                _fsync_slot_file(target)
            except OSError as error:
                raise unconfirmed(UnconfirmedReason.FILE_FSYNC_FAILED, f"fsync du fichier du slot en échec ({error}).") from error
        try:
            anchor.barrier()
        except OSError as error:
            raise unconfirmed(UnconfirmedReason.DIRECTORY_FSYNC_FAILED, f"fsync du répertoire en échec ({error}).") from error
        if not _parent_unchanged(anchor):
            raise unconfirmed(UnconfirmedReason.PARENT_CHANGED, "Le répertoire parent n'est plus celui tenu par la confirmation.")
        try:
            again = os.lstat(target)
        except OSError:
            raise unconfirmed(UnconfirmedReason.SLOT_MISSING, "Le slot a disparu pendant la confirmation.") from None
        if (again.st_dev, again.st_ino) != (slot.st_dev, slot.st_ino):
            raise unconfirmed(UnconfirmedReason.SLOT_IDENTITY_CHANGED, "Le slot a changé de fichier pendant la confirmation.")
        return LinkPublication(
            destination=target, state=PublicationState.PUBLISHED_DURABLE, durability_profile=durability, operation=PublicationOperation.RECONFIRMED,
            identity=identity, publication_id=uuid.uuid4().hex, writer_pid=os.getpid(), temp_path=None, temp_disposition=TempDisposition.NOT_CREATED)
    finally:
        anchor.close()
