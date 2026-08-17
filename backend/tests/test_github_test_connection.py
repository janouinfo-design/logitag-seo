"""Tests for POST /api/sites/{site_id}/test-github endpoint.

Covers:
1. Missing GitHub config → 400.
2. Fake token → 400 (third-party credential error, distinct from session 401).
3. Unit-level mock tests for the 3 branches of the 404 fallback logic:
   (a) repo exists and size==0 → "VIDE" + "README" message
   (b) repo exists and size>0 → "la branche" + "introuvable"
   (c) repo check != 200 → "introuvable ou inaccessible avec ce token"
4. Regression on PATCH /api/sites/{site_id} to save github_* and confirm
   github_token is never returned in clear via GET /api/sites/{site_id}.
"""
import os
import sys
import asyncio
import pytest
import requests
from unittest.mock import AsyncMock, patch, MagicMock

sys.path.insert(0, "/app/backend")

# Load REACT_APP_BACKEND_URL from frontend/.env if not in environment
if not os.environ.get("REACT_APP_BACKEND_URL"):
    try:
        with open("/app/frontend/.env") as fh:
            for line in fh:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    os.environ["REACT_APP_BACKEND_URL"] = line.split("=", 1)[1].strip()
                    break
    except FileNotFoundError:
        pass

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL must be set"
SITE_ID = "b3bec42d-2117-4f73-93b9-a0adc3b47a38"
EMAIL = "demo@logirent.fr"
PASSWORD = "demo1234"


@pytest.fixture(scope="module")
def api_client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    r = s.post(f"{BASE_URL}/api/auth/login", json={"email": EMAIL, "password": PASSWORD}, timeout=15)
    assert r.status_code == 200, f"login failed: {r.status_code} {r.text[:200]}"
    token = r.json().get("token")
    assert token, "no token in login response"
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


@pytest.fixture(scope="module", autouse=True)
def cleanup_github_config(api_client):
    """After the module: clear the github_* fields so we don't pollute the demo site."""
    yield
    api_client.patch(
        f"{BASE_URL}/api/sites/{SITE_ID}",
        json={
            "github_token": "",
            "github_owner": "",
            "github_repo": "",
            "github_branch": "main",
            "github_folder": "",
            "github_public_url": "",
        },
        timeout=15,
    )


# ---------- Live endpoint tests ------------------------------------------------
class TestTestGithubEndpoint:
    def test_missing_config_returns_400(self, api_client):
        # First wipe github config
        r = api_client.patch(
            f"{BASE_URL}/api/sites/{SITE_ID}",
            json={"github_token": "", "github_owner": "", "github_repo": ""},
            timeout=15,
        )
        assert r.status_code == 200

        # Verify token not leaked in GET
        g = api_client.get(f"{BASE_URL}/api/sites/{SITE_ID}", timeout=15)
        assert g.status_code == 200
        body = g.json()
        assert "github_token" not in body, "raw github_token must NOT be present in GET response"
        assert body.get("has_github_token") is False

        r = api_client.post(f"{BASE_URL}/api/sites/{SITE_ID}/test-github", timeout=15)
        assert r.status_code == 400
        detail = r.json().get("detail", "")
        assert "Configurez d'abord" in detail or "github_token" in detail

    def test_fake_token_returns_400(self, api_client):
        # Patch with a fake token / owner / repo
        r = api_client.patch(
            f"{BASE_URL}/api/sites/{SITE_ID}",
            json={
                "github_token": "ghp_faketoken1234567890abcdefFAKEfake",
                "github_owner": "someuser",
                "github_repo": "somerepo",
                "github_branch": "main",
                "github_folder": "",
            },
            timeout=15,
        )
        assert r.status_code == 200, f"PATCH failed: {r.status_code} {r.text[:200]}"

        # Regression: GET must not expose raw token
        g = api_client.get(f"{BASE_URL}/api/sites/{SITE_ID}", timeout=15)
        pub = g.json()
        assert "github_token" not in pub
        assert pub.get("has_github_token") is True
        assert pub.get("github_owner") == "someuser"
        assert pub.get("github_repo") == "somerepo"

        # Now test-github should return 400 (third-party credential error, not session 401)
        r = api_client.post(f"{BASE_URL}/api/sites/{SITE_ID}/test-github", timeout=20)
        assert r.status_code == 400, f"expected 400 got {r.status_code}: {r.text[:200]}"
        detail = r.json().get("detail", "")
        assert "Token GitHub invalide" in detail or "expiré" in detail


# ---------- Unit tests for the 404 branch logic --------------------------------
# We import the endpoint function directly and monkeypatch httpx.AsyncClient.

class _FakeResp:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
    """Async context manager returning a client whose .get returns queued responses."""

    def __init__(self, responses):
        # responses: list of _FakeResp returned in order for successive get calls
        self._responses = list(responses)
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, params=None):
        self.calls.append((url, params))
        if not self._responses:
            return _FakeResp(500, text="no response queued")
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_unit_404_branch_a_repo_empty(monkeypatch):
    import routes_publish as rp
    from fastapi import HTTPException

    async def fake_get_user_site(site_id, user):
        return {
            "id": "s1",
            "github_token": "enc_tok",
            "github_owner": "own",
            "github_repo": "rep",
            "github_branch": "main",
            "github_folder": "",
        }

    monkeypatch.setattr(rp, "_get_user_site", fake_get_user_site)
    monkeypatch.setattr(rp, "dec", lambda v: "plaintext_token" if v else None)

    responses = [
        _FakeResp(404, text="Not Found"),
        _FakeResp(200, json_data={"size": 0}),
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(rp.httpx, "AsyncClient", lambda *a, **kw: fake)

    with pytest.raises(HTTPException) as exc:
        await rp.test_github_connection("s1", user={"id": "u1"})
    assert exc.value.status_code == 404
    msg = exc.value.detail
    assert "VIDE" in msg
    assert "README" in msg


@pytest.mark.asyncio
async def test_unit_404_branch_b_repo_exists_branch_missing(monkeypatch):
    import routes_publish as rp
    from fastapi import HTTPException

    async def fake_get_user_site(site_id, user):
        return {
            "id": "s1",
            "github_token": "enc",
            "github_owner": "own",
            "github_repo": "rep",
            "github_branch": "develop",
            "github_folder": "",
        }

    monkeypatch.setattr(rp, "_get_user_site", fake_get_user_site)
    monkeypatch.setattr(rp, "dec", lambda v: "plaintext_token" if v else None)

    responses = [
        _FakeResp(404, text="Not Found"),
        _FakeResp(200, json_data={"size": 42}),
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(rp.httpx, "AsyncClient", lambda *a, **kw: fake)

    with pytest.raises(HTTPException) as exc:
        await rp.test_github_connection("s1", user={"id": "u1"})
    assert exc.value.status_code == 404
    msg = exc.value.detail
    assert "la branche" in msg
    assert "introuvable" in msg
    assert "VIDE" not in msg


@pytest.mark.asyncio
async def test_unit_404_branch_c_repo_inaccessible(monkeypatch):
    import routes_publish as rp
    from fastapi import HTTPException

    async def fake_get_user_site(site_id, user):
        return {
            "id": "s1",
            "github_token": "enc",
            "github_owner": "own",
            "github_repo": "rep",
            "github_branch": "main",
            "github_folder": "",
        }

    monkeypatch.setattr(rp, "_get_user_site", fake_get_user_site)
    monkeypatch.setattr(rp, "dec", lambda v: "plaintext_token" if v else None)

    responses = [
        _FakeResp(404, text="Not Found"),
        _FakeResp(404, text="Not Found"),  # repo check also 404
    ]
    fake = _FakeClient(responses)
    monkeypatch.setattr(rp.httpx, "AsyncClient", lambda *a, **kw: fake)

    with pytest.raises(HTTPException) as exc:
        await rp.test_github_connection("s1", user={"id": "u1"})
    assert exc.value.status_code == 404
    msg = exc.value.detail
    assert "introuvable ou inaccessible avec ce token" in msg
