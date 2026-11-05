"""
Staff accounts and login (auth_service.py + the /api/auth and /api/admin
endpoints): hashed passwords, server-side sessions, admin-only staff creation.
Every test runs against its own throw-away SQLite file.
"""

import sqlite3

import pytest
from fastapi.testclient import TestClient

import app as app_module
import auth_service

client = TestClient(app_module.app)


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("KHANNA_AUTH_DB", str(tmp_path / "users.db"))
    auth_service._failures.clear()
    yield


def _login(email="admin@khannatravels.com", password="admin123"):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_first_run_creates_the_two_shipped_accounts():
    admin = _login().json()
    assert admin["user"] == {"email": "admin@khannatravels.com", "name": "Admin", "role": "admin"}
    staff = _login("customercare@khannatravels.com", "khanna123").json()
    assert staff["user"]["role"] == "staff"


def test_passwords_are_stored_hashed_and_never_returned(tmp_path):
    body = _login().json()
    assert "password" not in str(body).lower().replace("password_hash", "")
    row = sqlite3.connect(str(tmp_path / "users.db")).execute("SELECT password_hash FROM users WHERE email='admin@khannatravels.com'").fetchone()
    assert row[0].startswith("scrypt$") and "admin123" not in row[0]
    listing = client.get("/api/admin/staff", headers=_bearer(body["token"])).json()
    assert "password" not in str(listing).lower()


def test_wrong_password_and_unknown_user_are_refused_with_the_same_message():
    a = _login(password="nope")
    b = _login("ghost@example.com", "whatever1")
    assert a.status_code == b.status_code == 401
    assert a.json()["detail"] == b.json()["detail"] == "Invalid email or password."


def test_repeated_wrong_passwords_are_paused():
    for _ in range(5):
        assert _login(password="bad").status_code == 401
    assert _login().status_code == 429  # even the right password waits


def test_me_logout_and_token_checks():
    token = _login().json()["token"]
    assert client.get("/api/auth/me", headers=_bearer(token)).json()["user"]["email"] == "admin@khannatravels.com"
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=_bearer("not-a-token")).status_code == 401
    client.post("/api/auth/logout", headers=_bearer(token))
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401


def test_only_an_admin_can_manage_staff():
    staff_token = _login("customercare@khannatravels.com", "khanna123").json()["token"]
    h = _bearer(staff_token)
    assert client.get("/api/admin/staff", headers=h).status_code == 403
    assert client.post("/api/admin/staff", headers=h, json={"name": "X Y", "email": "x@y.com", "password": "longenough1"}).status_code == 403
    assert client.post("/api/admin/staff/reset-password", headers=h, json={"email": "admin@khannatravels.com", "newPassword": "longenough1"}).status_code == 403
    assert client.post("/api/admin/staff/remove", headers=h, json={"email": "admin@khannatravels.com"}).status_code == 403
    assert client.get("/api/admin/staff").status_code == 401


def test_admin_creates_a_staff_login_that_works():
    admin = _bearer(_login().json()["token"])
    r = client.post("/api/admin/staff", headers=admin, json={"name": "Pooja Shah", "email": "Pooja@KhannaTravels.com", "password": "secret-pass-1"})
    assert r.status_code == 200, r.text
    assert r.json()["user"] == {"email": "pooja@khannatravels.com", "name": "Pooja Shah", "role": "staff"}
    login = _login("pooja@khannatravels.com", "secret-pass-1")
    assert login.status_code == 200 and login.json()["user"]["role"] == "staff"
    emails = [u["email"] for u in client.get("/api/admin/staff", headers=admin).json()["staff"]]
    assert "pooja@khannatravels.com" in emails


@pytest.mark.parametrize(
    "payload, status",
    [
        ({"name": "", "email": "a@b.com", "password": "longenough1"}, 400),
        ({"name": "A B", "email": "not-an-email", "password": "longenough1"}, 400),
        ({"name": "A B", "email": "a@b.com", "password": "short"}, 400),
        ({"name": "A B", "email": "admin@khannatravels.com", "password": "longenough1"}, 409),
    ],
)
def test_create_staff_validation(payload, status):
    admin = _bearer(_login().json()["token"])
    assert client.post("/api/admin/staff", headers=admin, json=payload).status_code == status


def test_reset_password_signs_the_person_out_and_the_new_password_works():
    admin = _bearer(_login().json()["token"])
    old = _login("customercare@khannatravels.com", "khanna123").json()["token"]
    r = client.post("/api/admin/staff/reset-password", headers=admin, json={"email": "customercare@khannatravels.com", "newPassword": "brand-new-pass"})
    assert r.status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(old)).status_code == 401
    assert _login("customercare@khannatravels.com", "khanna123").status_code == 401
    assert _login("customercare@khannatravels.com", "brand-new-pass").status_code == 200


def test_remove_staff_rules():
    admin = _bearer(_login().json()["token"])
    assert client.post("/api/admin/staff/remove", headers=admin, json={"email": "admin@khannatravels.com"}).status_code == 400  # not yourself
    old = _login("customercare@khannatravels.com", "khanna123").json()["token"]
    assert client.post("/api/admin/staff/remove", headers=admin, json={"email": "customercare@khannatravels.com"}).status_code == 200
    assert _login("customercare@khannatravels.com", "khanna123").status_code == 401
    assert client.get("/api/auth/me", headers=_bearer(old)).status_code == 401
    assert client.post("/api/admin/staff/remove", headers=admin, json={"email": "ghost@example.com"}).status_code == 404


def test_the_last_admin_cannot_be_removed_by_another_admin():
    admin = _bearer(_login().json()["token"])
    client.post("/api/admin/staff", headers=admin, json={"name": "Second Admin", "email": "second@khannatravels.com", "password": "second-pass-1", "role": "admin"})
    second = _bearer(_login("second@khannatravels.com", "second-pass-1").json()["token"])
    assert client.post("/api/admin/staff/remove", headers=second, json={"email": "admin@khannatravels.com"}).status_code == 200
    assert client.post("/api/admin/staff/remove", headers=admin, json={"email": "second@khannatravels.com"}).status_code == 401  # the removed admin's session is gone


def test_own_name_and_password_change():
    token = _login("customercare@khannatravels.com", "khanna123").json()["token"]
    h = _bearer(token)
    assert client.patch("/api/auth/profile", headers=h, json={"name": "  Visa   Desk "}).json()["user"]["name"] == "Visa Desk"
    assert client.patch("/api/auth/profile", headers=h, json={"name": "   "}).status_code == 400
    other_device = _login("customercare@khannatravels.com", "khanna123").json()["token"]
    bad = client.post("/api/auth/change-password", headers=h, json={"currentPassword": "wrong", "newPassword": "another-pass-1"})
    assert bad.status_code == 400
    short = client.post("/api/auth/change-password", headers=h, json={"currentPassword": "khanna123", "newPassword": "short"})
    assert short.status_code == 400
    ok = client.post("/api/auth/change-password", headers=h, json={"currentPassword": "khanna123", "newPassword": "another-pass-1"})
    assert ok.status_code == 200
    assert client.get("/api/auth/me", headers=h).status_code == 200            # this device stays signed in
    assert client.get("/api/auth/me", headers=_bearer(other_device)).status_code == 401  # others are signed out
    assert _login("customercare@khannatravels.com", "another-pass-1").status_code == 200


def test_expired_sessions_are_refused(monkeypatch):
    token = _login().json()["token"]
    real_time = auth_service.time.time
    monkeypatch.setattr(auth_service.time, "time", lambda: real_time() + auth_service.SESSION_TTL_SECONDS + 5)
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401
