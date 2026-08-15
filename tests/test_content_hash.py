"""
tests/test_content_hash.py — Tests de market_data/content_hash.py (AF-DATA-01).

Primitive de hash de contenu pour un fichier CSV local générique — pas encore un DatasetVersion
complet, pas encore branchée dans job_store.py (voir EPICS_AND_TICKETS.md, AF-DATA-01). Le hash
porte sur les octets bruts du fichier source, jamais sur le DataFrame pandas résultant d'un
parsing. Vérifie le déterminisme, la sensibilité au contenu, l'indépendance au chemin, le
streaming (pas de lecture intégrale) et le comportement explicite sur fichier absent.
"""

from __future__ import annotations

import hashlib
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.content_hash import content_hash

# Vecteur de test officiel FIPS 180-4 (Appendix B.1) : SHA-256("abc").
_ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_content_hash_matches_known_sha256_vector(tmp_path):
    """A. Contenu connu -> SHA-256 attendu exactement (pas seulement len == 64)."""
    path = tmp_path / "abc.csv"
    path.write_bytes(b"abc")

    assert content_hash(path) == _ABC_SHA256


def test_content_hash_is_independent_of_the_file_path(tmp_path):
    """B. Mêmes octets, deux chemins différents -> même hash."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b" / "nested"
    dir_a.mkdir()
    dir_b.mkdir(parents=True)

    content = b"time,open,high,low,close\n2024-01-01,1,2,0.5,1.5\n"
    path_a = dir_a / "nasdaq_3m.csv"
    path_b = dir_b / "a_totally_different_name.csv"
    path_a.write_bytes(content)
    path_b.write_bytes(content)

    assert content_hash(path_a) == content_hash(path_b)


def test_content_hash_changes_when_a_single_byte_changes(tmp_path):
    """C. Changement d'un seul octet -> hash différent."""
    path = tmp_path / "data.csv"
    path.write_bytes(b"time,close\n2024-01-01,100.0\n")
    hash_before = content_hash(path)

    original = bytearray(path.read_bytes())
    original[-2] = original[-2] ^ 0x01  # bascule un seul bit du dernier caractère utile
    path.write_bytes(bytes(original))
    hash_after = content_hash(path)

    assert hash_before != hash_after


def test_content_hash_of_empty_file_is_the_standard_empty_sha256(tmp_path):
    """D. Fichier vide -> SHA-256 standard du contenu vide."""
    path = tmp_path / "empty.csv"
    path.write_bytes(b"")

    assert content_hash(path) == hashlib.sha256(b"").hexdigest()


def test_content_hash_streaming_matches_full_read_reference(tmp_path):
    """E. Fichier plus gros qu'un chunk -> hash identique à hashlib.sha256() du contenu entier.

    Le contenu est déterministe (pas aléatoire) pour que le test soit reproductible : motif
    répété jusqu'à dépasser toute taille de chunk raisonnable (quelques Mo).
    """
    path = tmp_path / "large.csv"
    row = b"2024-01-01T00:00:00,17500.25,17510.75,17490.00,17505.50,1234\n"
    content = row * 200_000  # ~ plusieurs Mo, dépasse largement un chunk de lecture raisonnable
    path.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()

    assert content_hash(path) == expected


def test_content_hash_never_modifies_the_source_file(tmp_path):
    """F. Le fichier source n'est jamais modifié par le calcul du hash."""
    path = tmp_path / "untouched.csv"
    original_bytes = b"time,close\n2024-01-01,100.0\n2024-01-02,101.5\n"
    path.write_bytes(original_bytes)
    original_mtime = path.stat().st_mtime_ns

    content_hash(path)

    assert path.read_bytes() == original_bytes
    assert path.stat().st_mtime_ns == original_mtime


def test_content_hash_raises_a_clear_error_on_missing_file(tmp_path):
    """G. Comportement explicite sur fichier inexistant -> FileNotFoundError."""
    missing = tmp_path / "does_not_exist.csv"

    with pytest.raises(FileNotFoundError):
        content_hash(missing)


def test_content_hash_accepts_a_plain_string_path(tmp_path):
    """Le seam doit rester utilisable avec un chemin str, pas seulement Path (cohérence avec le
    reste de market_data/, ex. build_backtest_manifest(repo_dir=...))."""
    path = tmp_path / "abc.csv"
    path.write_bytes(b"abc")

    assert content_hash(str(path)) == _ABC_SHA256


def test_content_hash_is_deterministic_across_repeated_calls(tmp_path):
    """Bonus déterminisme : deux appels consécutifs sur le même fichier donnent le même résultat
    (pas seulement deux fichiers différents avec le même contenu, voir test B)."""
    path = tmp_path / "repeat.csv"
    path.write_bytes(b"time,close\n2024-01-01,100.0\n")

    assert content_hash(path) == content_hash(path)
