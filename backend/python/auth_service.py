"""
Khanna Travels & Holidays — staff accounts and login sessions
================================================================

Real, server-side accounts for the app (replaces the hard-coded demo list
that used to live in js/core/auth.js):

  * Accounts live in a small SQLite file (default: backend/python/data/
    khanna_users.db, override with KHANNA_AUTH_DB). Passwords are stored as
    salted scrypt hashes — never in plain text, never returned by any
    endpoint.
  * Logging in returns a random session token; only a SHA-256 hash of the
    token is stored, so a copy of the database cannot be replayed as
    sessions. Sessions expire after 12 hours and can be revoked (logout,
    password change, removing an account).
  * Only an admin can create or remove staff accounts or reset a password
    (enforced here, on the server — the browser merely hides the buttons).
  * Repeated wrong passwords for one email are slowed down (5 failures in 5
    minutes -> a 5-minute pause).

First start: if there are no accounts at all, the two accounts the app has
always shipped with are created (admin@khannatravels.com and
customercare@khannatravels.com) so nobody is locked out. Set
KHANNA_ADMIN_EMAIL / KHANNA_ADMIN_PASSWORD (and optionally
KHANNA_STAFF_EMAIL / KHANNA_STAFF_PASSWORD) in the environment to choose
different first-run credentials. Either way, change them from the
Profile & Settings page.

Everything here is Python standard library only.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Optional

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(_THIS_DIR, "data", "khanna_users.db")

SESSION_TTL_SECONDS = 12 * 60 * 60
MIN_PASSWORD_LENGTH = 8
ROLES = ("admin", "staff")

_FAIL_LIMIT = 5
_FAIL_WINDOW_SECONDS = 5 * 60

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_lock = threading.RLock()
_failures: dict[str, list[float]] = {}


class AuthError(Exception):
    """A request the caller should be told about (carries an HTTP status)."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


def db_path() -> str:
    return os.environ.get("KHANNA_AUTH_DB") or DEFAULT_DB_PATH


@contextmanager
def _db():
    path = db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _lock:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            _ensure_schema(conn)
            yield conn
            conn.commit()
        finally:
            conn.close()


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               email TEXT PRIMARY KEY,
               name TEXT NOT NULL,
               role TEXT NOT NULL,
               password_hash TEXT NOT NULL,
               created_at REAL NOT NULL,
               created_by TEXT
           )"""
    )
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sessions (
               token_hash TEXT PRIMARY KEY,
               email TEXT NOT NULL,
               expires_at REAL NOT NULL
           )"""
    )
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        _seed_first_accounts(conn)


def _seed_first_accounts(conn: sqlite3.Connection) -> None:
    now = time.time()
    seeds = [
        (
            os.environ.get("KHANNA_ADMIN_EMAIL", "admin@khannatravels.com"),
            "Admin",
            "admin",
            os.environ.get("KHANNA_ADMIN_PASSWORD", "admin123"),
        ),
        (
            os.environ.get("KHANNA_STAFF_EMAIL", "customercare@khannatravels.com"),
            "Visa Team",
            "staff",
            os.environ.get("KHANNA_STAFF_PASSWORD", "khanna123"),
        ),
    ]
    for email, name, role, password in seeds:
        conn.execute(
            "INSERT OR IGNORE INTO users (email, name, role, password_hash, created_at, created_by) VALUES (?,?,?,?,?,?)",
            (email.strip().lower(), name, role, hash_password(password), now, "first-run"),
        )


# ---------------------------------------------------------------------------
# Passwords and tokens
# ---------------------------------------------------------------------------

_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(
        _SCRYPT_N, _SCRYPT_R, _SCRYPT_P, base64.b64encode(salt).decode(), base64.b64encode(digest).decode()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=int(n), r=int(r), p=int(p), dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _normalise_email(email: Optional[str]) -> str:
    return (email or "").strip().lower()


def _check_password_rules(password: Optional[str]) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise AuthError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.", 400)
    if len(password) > 200:
        raise AuthError("Password is too long.", 400)
    return password


def _public(row: sqlite3.Row) -> dict:
    return {"email": row["email"], "name": row["name"], "role": row["role"]}


# ---------------------------------------------------------------------------
# Login / sessions
# ---------------------------------------------------------------------------


def _recent_failures(email: str) -> list[float]:
    cutoff = time.time() - _FAIL_WINDOW_SECONDS
    recent = [t for t in _failures.get(email, []) if t > cutoff]
    _failures[email] = recent
    return recent


def login(email: str, password: str) -> dict:
    email = _normalise_email(email)
    with _lock:
        if len(_recent_failures(email)) >= _FAIL_LIMIT:
            raise AuthError("Too many wrong attempts. Please wait a few minutes and try again.", 429)
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        ok = bool(row) and verify_password(password or "", row["password_hash"])
        if not ok:
            with _lock:
                _failures.setdefault(email, []).append(time.time())
            raise AuthError("Invalid email or password.", 401)
        with _lock:
            _failures.pop(email, None)
        token = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
        conn.execute(
            "INSERT INTO sessions (token_hash, email, expires_at) VALUES (?,?,?)",
            (_token_hash(token), email, now + SESSION_TTL_SECONDS),
        )
        return {"token": token, "user": _public(row)}


def user_for_token(token: Optional[str]) -> dict:
    """The signed-in user for a session token, or AuthError(401)."""
    if not token:
        raise AuthError("Please log in.", 401)
    with _db() as conn:
        session = conn.execute(
            "SELECT email, expires_at FROM sessions WHERE token_hash = ?", (_token_hash(token),)
        ).fetchone()
        if not session or session["expires_at"] < time.time():
            raise AuthError("Your session has ended. Please log in again.", 401)
        row = conn.execute("SELECT * FROM users WHERE email = ?", (session["email"],)).fetchone()
        if not row:
            raise AuthError("This account no longer exists.", 401)
        return _public(row)


def require_admin(token: Optional[str]) -> dict:
    user = user_for_token(token)
    if user["role"] != "admin":
        raise AuthError("Only an admin can do this.", 403)
    return user


def logout(token: Optional[str]) -> None:
    if not token:
        return
    with _db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))


# ---------------------------------------------------------------------------
# Own account
# ---------------------------------------------------------------------------


def update_own_name(token: str, name: str) -> dict:
    user = user_for_token(token)
    name = re.sub(r"\s+", " ", (name or "").strip())
    if not name:
        raise AuthError("Please enter a name.", 400)
    if len(name) > 80:
        raise AuthError("That name is too long.", 400)
    with _db() as conn:
        conn.execute("UPDATE users SET name = ? WHERE email = ?", (name, user["email"]))
        return _public(conn.execute("SELECT * FROM users WHERE email = ?", (user["email"],)).fetchone())


def change_own_password(token: str, current_password: str, new_password: str) -> None:
    user = user_for_token(token)
    _check_password_rules(new_password)
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (user["email"],)).fetchone()
        if not verify_password(current_password or "", row["password_hash"]):
            raise AuthError("Your current password is not correct.", 400)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hash_password(new_password), user["email"]))
        # Every other device is signed out; this one keeps its session.
        conn.execute("DELETE FROM sessions WHERE email = ? AND token_hash != ?", (user["email"], _token_hash(token)))


# ---------------------------------------------------------------------------
# Admin: staff accounts
# ---------------------------------------------------------------------------


def list_staff(token: str) -> list[dict]:
    require_admin(token)
    with _db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY role, lower(name)").fetchall()
        return [
            dict(_public(r), createdAt=r["created_at"], createdBy=r["created_by"] or "")
            for r in rows
        ]


def create_staff(token: str, name: str, email: str, password: str, role: str = "staff") -> dict:
    admin = require_admin(token)
    name = re.sub(r"\s+", " ", (name or "").strip())
    email = _normalise_email(email)
    if not name:
        raise AuthError("Please enter the staff member's name.", 400)
    if len(name) > 80:
        raise AuthError("That name is too long.", 400)
    if not _EMAIL_RE.match(email):
        raise AuthError("Please enter a valid email address.", 400)
    if role not in ROLES:
        raise AuthError("Role must be staff or admin.", 400)
    _check_password_rules(password)
    with _db() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("An account with this email already exists.", 409)
        conn.execute(
            "INSERT INTO users (email, name, role, password_hash, created_at, created_by) VALUES (?,?,?,?,?,?)",
            (email, name, role, hash_password(password), time.time(), admin["email"]),
        )
        return _public(conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone())


def reset_staff_password(token: str, email: str, new_password: str) -> None:
    require_admin(token)
    email = _normalise_email(email)
    _check_password_rules(new_password)
    with _db() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
            raise AuthError("No account with that email.", 404)
        conn.execute("UPDATE users SET password_hash = ? WHERE email = ?", (hash_password(new_password), email))
        conn.execute("DELETE FROM sessions WHERE email = ?", (email,))


def remove_staff(token: str, email: str) -> None:
    admin = require_admin(token)
    email = _normalise_email(email)
    if email == admin["email"]:
        raise AuthError("You can't remove your own account.", 400)
    with _db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not row:
            raise AuthError("No account with that email.", 404)
        if row["role"] == "admin" and conn.execute("SELECT COUNT(*) FROM users WHERE role = 'admin'").fetchone()[0] <= 1:
            raise AuthError("The last admin account can't be removed.", 400)
        conn.execute("DELETE FROM users WHERE email = ?", (email,))
        conn.execute("DELETE FROM sessions WHERE email = ?", (email,))
