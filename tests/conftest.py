import os
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(scope="session")
def client():
    """A test client backed by a throwaway database with a known admin password."""
    tmp = tempfile.mkdtemp()
    os.environ["KYGS_DB"] = os.path.join(tmp, "test.db")
    os.environ["KYGS_ADMIN_PASSWORD"] = "TestAdmin123"

    from fastapi.testclient import TestClient
    from backend.app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def admin(client):
    """Authorised admin headers, with the first-login password change done."""
    res = client.post("/api/auth/login",
                      json={"username": "admin", "password": "TestAdmin123"})
    assert res.status_code == 200, res.text
    token = res.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    client.post("/api/auth/change-password",
                json={"current_password": "TestAdmin123", "new_password": "Workshop2025"},
                headers=headers)
    res = client.post("/api/auth/login",
                      json={"username": "admin", "password": "Workshop2025"})
    return {"Authorization": f"Bearer {res.json()['token']}"}
