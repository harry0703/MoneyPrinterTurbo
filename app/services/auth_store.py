"""Single-account login store for the webui.

Persists one account in sqlite (id fixed to 1, so only one row can ever
exist) with a PBKDF2 password hash. Login is protected by a lockout window
after repeated failures. The account email is never hardcoded here: the
caller reads it from config (app.login_email) and passes it in, the same
way every other credential in this project lives in config.toml, not source.
"""

import hashlib
import os
import secrets
import sqlite3
import string
import time
from contextlib import closing

from app.utils import utils

PBKDF2_ITERATIONS = 600_000
LOCKOUT_THRESHOLD = 5
LOCKOUT_SECONDS = 15 * 60
_PASSWORD_LENGTH = 20
_SYMBOLS = "!@#$%^&*()-_=+"


def _default_db_path() -> str:
    override = os.environ.get("MPT_AUTH_DB_PATH")
    if override:
        return override
    return os.path.join(utils.storage_dir(create=True), "auth.db")


def _connect(db_path: str | None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or _default_db_path())
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            iterations INTEGER NOT NULL,
            failed_attempts INTEGER NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0,
            created_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def _hash_password(password: str, salt: bytes, iterations: int) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, iterations
    ).hex()


def generate_strong_password(length: int = _PASSWORD_LENGTH) -> str:
    """Random password guaranteed to include lower/upper/digit/symbol chars."""
    groups = [string.ascii_lowercase, string.ascii_uppercase, string.digits, _SYMBOLS]
    alphabet = "".join(groups)
    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))
        if all(any(c in group for c in password) for group in groups):
            return password


def ensure_account(email: str, db_path: str | None = None) -> str | None:
    """Create the single account on first run, using the configured email.

    Returns the generated plaintext password when the account was just
    created, or ``None`` when it already existed (nothing to show again).
    """
    email = email.strip()
    if not email:
        raise ValueError("email is required to create the login account")

    with closing(_connect(db_path)) as conn:
        if conn.execute("SELECT 1 FROM users WHERE id = 1").fetchone():
            return None

        password = generate_strong_password()
        salt = secrets.token_bytes(16)
        password_hash = _hash_password(password, salt, PBKDF2_ITERATIONS)
        conn.execute(
            "INSERT INTO users "
            "(id, email, password_hash, salt, iterations, created_at) "
            "VALUES (1, ?, ?, ?, ?, ?)",
            (email, password_hash, salt.hex(), PBKDF2_ITERATIONS, time.time()),
        )
        conn.commit()
        return password


def verify_login(email: str, password: str, db_path: str | None = None) -> bool:
    """Check credentials against the single stored account, honoring lockout."""
    with closing(_connect(db_path)) as conn:
        row = conn.execute(
            "SELECT email, password_hash, salt, iterations, failed_attempts, locked_until "
            "FROM users WHERE id = 1"
        ).fetchone()
        if row is None:
            return False

        (
            stored_email,
            password_hash,
            salt_hex,
            iterations,
            failed_attempts,
            locked_until,
        ) = row
        now = time.time()
        if now < locked_until:
            return False

        # Hash is computed unconditionally so a wrong email doesn't short-circuit
        # the response time and leak which field was wrong.
        candidate_hash = _hash_password(password, bytes.fromhex(salt_hex), iterations)
        email_matches = secrets.compare_digest(
            email.strip().lower().encode("utf-8"), stored_email.encode("utf-8")
        )
        password_matches = secrets.compare_digest(
            candidate_hash.encode("utf-8"), password_hash.encode("utf-8")
        )

        if email_matches and password_matches:
            conn.execute(
                "UPDATE users SET failed_attempts = 0, locked_until = 0 WHERE id = 1"
            )
            conn.commit()
            return True

        failed_attempts += 1
        if failed_attempts >= LOCKOUT_THRESHOLD:
            conn.execute(
                "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = 1",
                (failed_attempts, now + LOCKOUT_SECONDS),
            )
        else:
            conn.execute(
                "UPDATE users SET failed_attempts = ? WHERE id = 1",
                (failed_attempts,),
            )
        conn.commit()
        return False
