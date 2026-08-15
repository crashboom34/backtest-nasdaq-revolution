"""
market_data/content_hash.py — Hash de contenu d'un fichier source local (AF-DATA-01).

Primitive générique et minimale : identité de contenu d'un artefact fichier (ses octets exacts),
indépendante de son chemin, de son nom et de tout horodatage. N'est PAS encore un `DatasetVersion`
au sens de docs/architecture/DOMAIN_MODEL.md §2 — c'est le hash de l'artefact source brut, qu'un
futur ticket pourra relier à un `DatasetVersion` catalogué (voir EPICS_AND_TICKETS.md, AF-DATA-01
"Out of scope").

Volontairement séparée de `market_data.eodhd.storage._content_hash()` (privée, sémantique
différente : identité asset/timeframe/ticker/source + contenu canonique EODHD) — ce module ne
dépend d'aucun sous-système fournisseur, pour rester réutilisable par n'importe quelle source
locale future (CSV, ou autre) sans coupler `market_data` à EODHD ni à un fournisseur particulier.

Lecture streamée par blocs : la mémoire utilisée est bornée indépendamment de la taille du
fichier, jamais un `Path.read_bytes()`/`f.read()` intégral.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

# Détail d'implémentation, jamais exposé à l'appelant : taille des blocs lus pour rester à
# mémoire bornée. 1 MiB est un compromis standard entre nombre d'appels système et empreinte
# mémoire, sans signification fonctionnelle.
_CHUNK_SIZE_BYTES = 1024 * 1024


def content_hash(path: Union[str, Path]) -> str:
    """SHA-256 hexadécimal des octets exacts du fichier à `path`.

    Propriétés garanties :
    - déterministe et stable (mêmes octets -> même hash, toujours) ;
    - indépendante du chemin/nom du fichier (seul le contenu compte) ;
    - un seul octet différent -> hash différent ;
    - jamais de timestamp ni de métadonnée du fichier inclus dans le hash ;
    - le fichier n'est jamais modifié (lecture seule) ;
    - lecture streamée par blocs de `_CHUNK_SIZE_BYTES` -> mémoire bornée, indépendante de la
      taille du fichier.

    Lève `FileNotFoundError` si `path` n'existe pas — propagée telle quelle depuis `open()`,
    pas de message custom qui masquerait l'erreur standard.
    """
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            chunk = handle.read(_CHUNK_SIZE_BYTES)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()
