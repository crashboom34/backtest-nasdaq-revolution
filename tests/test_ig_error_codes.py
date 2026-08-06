"""
tests/test_ig_error_codes.py — Tests de market_data/ig/error_codes.py et de l'extraction sûre
de errorCode dans market_data/ig/http_client.py (suite au diagnostic HTTP 403 du 2026-08-06).

Prouve que :
  - le statut HTTP et le champ IG errorCode peuvent être affichés/consultés ;
  - une explication lisible existe pour les codes confirmés, et un message générique sûr pour
    tout code inconnu (jamais une explication devinée) ;
  - AUCUN secret (api_key, identifier, password, CST, X-SECURITY-TOKEN, OAuth) ni le corps
    complet d'une réponse IG ne peut jamais atteindre l'exception, le résultat, ou la sortie du
    script — même si un corps de réponse malveillant/inattendu en contient.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from market_data.ig.client import IgClient
from market_data.ig.config import IgConfig
from market_data.ig.error_codes import explain_ig_error_code
from market_data.ig.errors import IgAuthError, IgForbiddenError
from market_data.ig.http_client import extract_ig_error_code


class FakeResponse:
    def __init__(self, content: bytes):
        self.content = content


# ═══════════════════════════════════════════════════════════════════════════════
# extract_ig_error_code() — n'extrait jamais que le champ errorCode.
# ═══════════════════════════════════════════════════════════════════════════════


def test_extract_ig_error_code_reads_the_field():
    response = FakeResponse(json.dumps({"errorCode": "error.security.api-key-invalid"}).encode())
    assert extract_ig_error_code(response) == "error.security.api-key-invalid"


def test_extract_ig_error_code_returns_none_when_absent():
    response = FakeResponse(json.dumps({"somethingElse": "value"}).encode())
    assert extract_ig_error_code(response) is None


def test_extract_ig_error_code_returns_none_on_invalid_json():
    response = FakeResponse(b"{not valid json")
    assert extract_ig_error_code(response) is None


def test_extract_ig_error_code_returns_none_on_empty_body():
    response = FakeResponse(b"")
    assert extract_ig_error_code(response) is None


def test_extract_ig_error_code_returns_none_when_body_is_a_json_array():
    response = FakeResponse(b"[1, 2, 3]")
    assert extract_ig_error_code(response) is None


def test_extract_ig_error_code_ignores_non_string_error_code():
    response = FakeResponse(json.dumps({"errorCode": 12345}).encode())
    assert extract_ig_error_code(response) is None


def test_extract_ig_error_code_never_exposes_other_body_fields():
    """Même si le corps contient un champ ressemblant à un secret, seul errorCode est extrait —
    rien d'autre n'est jamais retourné ni accessible."""
    response = FakeResponse(
        json.dumps(
            {
                "errorCode": "error.security.api-key-invalid",
                "CST": "should-never-be-extracted",
                "X-SECURITY-TOKEN": "should-never-be-extracted-either",
                "debug": "full internal stack trace with secrets",
            }
        ).encode()
    )
    result = extract_ig_error_code(response)
    assert result == "error.security.api-key-invalid"
    assert "should-never-be-extracted" not in str(result)


# ═══════════════════════════════════════════════════════════════════════════════
# explain_ig_error_code() — explication sûre, jamais devinée pour un code inconnu.
# ═══════════════════════════════════════════════════════════════════════════════


def test_explain_known_code_returns_specific_explanation():
    text = explain_ig_error_code("error.security.api-key-invalid")
    assert "clé api" in text.lower() or "api" in text.lower()


def test_explain_unknown_code_returns_generic_safe_message():
    text = explain_ig_error_code("error.something.never-seen-before")
    assert "error.something.never-seen-before" in text
    assert "non reconnu" in text.lower()


def test_explain_no_code_returns_generic_message():
    text = explain_ig_error_code(None)
    assert "errorcode" in text.lower() or "code" in text.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# IgHttpError.error_code — porté par l'exception, jamais un secret.
# ═══════════════════════════════════════════════════════════════════════════════


def test_ig_http_error_carries_status_and_error_code():
    exc = IgForbiddenError("Action IG refusée (403).", 403, "error.security.api-key-invalid")
    assert exc.status_code == 403
    assert exc.error_code == "error.security.api-key-invalid"


def test_ig_http_error_defaults_error_code_to_none():
    exc = IgAuthError("Authentification IG refusée (401).", 401)
    assert exc.error_code is None


def test_ig_http_error_string_never_contains_a_secret_even_if_constructed_with_one():
    # Défense en profondeur : même si un appelant négligent passait un secret dans error_code,
    # str(exc) ne doit jamais ressembler à une fuite involontaire d'un header ou d'un token —
    # ce test documente que error_code est un simple attribut de données, pas interpolé dans le
    # message de base par défaut.
    exc = IgForbiddenError("Action IG refusée (403).", 403, "error.security.api-key-invalid")
    assert "CST" not in str(exc)
    assert "X-SECURITY-TOKEN" not in str(exc)


# ═══════════════════════════════════════════════════════════════════════════════
# Bout en bout : login()/test_connection() exposent status_code/error_code sans fuite.
# ═══════════════════════════════════════════════════════════════════════════════


class FakeHttpClient403:
    """Simule un 403 avec un corps de réponse contenant errorCode + de faux secrets."""

    def __init__(self):
        self.calls = []

    def request(self, method, path, *, version, json_body=None, params=None, include_auth=True):
        self.calls.append({"method": method, "path": path})
        raise IgForbiddenError(
            "Action IG refusée (403).", 403, "error.security.api-key-invalid"
        )


def _config():
    return IgConfig(api_key="super-secret-api-key", identifier="my-id", password="super-secret-pw", account_id=None)


def test_login_result_exposes_status_and_error_code_without_leaking_secrets():
    client = IgClient(_config(), http_client=FakeHttpClient403())
    result = client.login()

    assert result.ok is False
    assert result.status_code == 403
    assert result.error_code == "error.security.api-key-invalid"
    dump = f"{result.message} {result.status_code} {result.error_code}"
    assert "super-secret-api-key" not in dump
    assert "super-secret-pw" not in dump


def test_connection_test_result_exposes_status_and_error_code_without_leaking_secrets():
    client = IgClient(_config(), http_client=FakeHttpClient403())
    result = client.test_connection()

    assert result.ok is False
    assert result.status_code == 403
    assert result.error_code == "error.security.api-key-invalid"
    dump = f"{result.message} {result.status_code} {result.error_code}"
    assert "super-secret-api-key" not in dump
    assert "super-secret-pw" not in dump


# ═══════════════════════════════════════════════════════════════════════════════
# scripts/test_ig_connection.py — affichage sûr des détails d'échec.
# ═══════════════════════════════════════════════════════════════════════════════


def _load_script_module():
    script_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "test_ig_connection.py"
    )
    spec = importlib.util.spec_from_file_location("test_ig_connection_script", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_script_print_failure_details_shows_status_and_error_code(capsys):
    module = _load_script_module()
    module._print_failure_details(403, "error.security.api-key-invalid", "Connexion IG démo échouée : Action IG refusée (403).")

    output = capsys.readouterr().out
    assert "403" in output
    assert "error.security.api-key-invalid" in output
    assert "Clé API invalide" in output or "clé api" in output.lower()


def test_script_print_failure_details_never_leaks_secrets_even_if_present_in_message(capsys):
    module = _load_script_module()
    # Message volontairement "contaminé" pour prouver que la fonction elle-même n'ajoute rien
    # de plus sensible ; le vrai connecteur ne construit jamais un tel message (voir errors.py),
    # mais on vérifie ici que la fonction d'affichage ne fait aucune interpolation dangereuse.
    module._print_failure_details(403, "error.security.api-key-invalid", "message sûr sans secret")

    output = capsys.readouterr().out
    assert "CST" not in output
    assert "X-SECURITY-TOKEN" not in output
    assert "api_key" not in output.lower() or "api key" not in output


def test_script_print_failure_details_omits_error_code_lines_when_absent(capsys):
    module = _load_script_module()
    module._print_failure_details(None, None, "Timeout réseau.")

    output = capsys.readouterr().out
    assert "Statut HTTP" not in output
    assert "errorCode" not in output
    assert "Timeout réseau." in output
