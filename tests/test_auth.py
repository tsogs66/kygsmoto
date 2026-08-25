"""Login, lockout, roles and permission boundaries."""


def test_health_needs_no_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_protected_route_rejects_anonymous(client):
    assert client.get("/api/items").status_code == 401


def test_bad_password_is_rejected(client):
    res = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid username or password"


def test_unknown_user_gives_identical_error(client):
    """Error text must not reveal whether the username exists."""
    res = client.post("/api/auth/login", json={"username": "ghost", "password": "wrong"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid username or password"


def test_admin_can_log_in_and_read_profile(client, admin):
    res = client.get("/api/auth/me", headers=admin)
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["username"] == "admin"
    assert body["user"]["must_change_password"] is False
    assert "users.manage" in body["permissions"]


def test_weak_passwords_are_refused(client, admin):
    res = client.post("/api/auth/users", headers=admin,
                      json={"username": "weakling", "password": "abc", "role": "cashier"})
    assert res.status_code == 400
    assert "at least 8 characters" in res.json()["detail"]


def test_cashier_cannot_reach_manager_functions(client, admin):
    created = client.post("/api/auth/users", headers=admin,
                          json={"username": "cashier1", "full_name": "Counter Staff",
                                "password": "Counter123", "role": "cashier"})
    assert created.status_code == 200

    login = client.post("/api/auth/login",
                        json={"username": "cashier1", "password": "Counter123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}

    assert client.get("/api/auth/users", headers=headers).status_code == 403
    assert client.get("/api/analytics/overview", headers=headers).status_code == 403
    assert client.post("/api/inventory/adjust", headers=headers,
                       json={"item_id": 1, "qty_delta": 1, "reason": "found"}).status_code == 403
    # But the till itself works.
    assert client.get("/api/items", headers=headers).status_code == 200


def test_last_admin_cannot_be_demoted(client, admin):
    me = client.get("/api/auth/me", headers=admin).json()["user"]
    res = client.patch(f"/api/auth/users/{me['id']}", headers=admin, json={"role": "cashier"})
    assert res.status_code == 400
    assert "last active administrator" in res.json()["detail"]


def test_logout_invalidates_the_token(client, admin):
    login = client.post("/api/auth/login",
                        json={"username": "cashier1", "password": "Counter123"})
    headers = {"Authorization": f"Bearer {login.json()['token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    client.post("/api/auth/logout", headers=headers)
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_repeated_failures_lock_the_account(client, admin):
    client.post("/api/auth/users", headers=admin,
                json={"username": "locktest", "password": "LockMe123", "role": "cashier"})
    for _ in range(5):
        client.post("/api/auth/login", json={"username": "locktest", "password": "nope"})
    res = client.post("/api/auth/login", json={"username": "locktest", "password": "LockMe123"})
    assert res.status_code == 423
    assert "locked" in res.json()["detail"].lower()
