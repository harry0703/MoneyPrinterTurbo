import sqlite3
import string

import pytest

from app.services import auth_store

TEST_EMAIL = "someone@example.com"


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "auth.db")


def test_ensure_account_creates_single_account_with_generated_password(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    assert password is not None
    assert len(password) >= 16
    assert any(c in string.ascii_lowercase for c in password)
    assert any(c in string.ascii_uppercase for c in password)
    assert any(c in string.digits for c in password)
    assert any(c not in string.ascii_letters + string.digits for c in password)


def test_ensure_account_is_idempotent(db_path):
    first = auth_store.ensure_account(TEST_EMAIL, db_path)
    second = auth_store.ensure_account(TEST_EMAIL, db_path)

    assert first is not None
    assert second is None

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert count == 1


def test_verify_login_accepts_correct_credentials(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is True


def test_verify_login_rejects_wrong_password(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)

    assert auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path) is False


def test_verify_login_rejects_wrong_email(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    assert auth_store.verify_login("someone-else@example.com", password, db_path) is False


def test_verify_login_rejects_when_account_missing(db_path):
    assert auth_store.verify_login(TEST_EMAIL, "anything", db_path) is False


def test_verify_login_locks_out_after_five_failed_attempts(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        assert (
            auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path) is False
        )

    # Correct password rejected while locked out.
    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is False


def test_verify_login_unlocks_after_lockout_window_passes(db_path, monkeypatch):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(auth_store.time, "time", lambda: fake_now[0])

    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)

    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is False

    fake_now[0] += auth_store.LOCKOUT_SECONDS + 1

    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is True


def test_verify_login_wrong_email_does_not_count_toward_lockout(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    # Way more than LOCKOUT_THRESHOLD failed attempts, all against an email
    # that doesn't match the account: the real account must stay unlocked.
    for _ in range(auth_store.LOCKOUT_THRESHOLD * 3):
        auth_store.verify_login("someone-else@example.com", "wrong", db_path)

    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is True


def test_verify_login_backoff_grows_and_caps_at_max_seconds(db_path, monkeypatch):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    fake_now = [1_000_000.0]
    monkeypatch.setattr(auth_store.time, "time", lambda: fake_now[0])

    # First lockout: exactly LOCKOUT_THRESHOLD failures -> base window.
    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)

    fake_now[0] += auth_store.LOCKOUT_SECONDS + 1
    # One more failure right after unlocking should escalate the window,
    # but never past LOCKOUT_MAX_SECONDS.
    auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)
    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is False

    fake_now[0] += auth_store.LOCKOUT_MAX_SECONDS + 1
    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is True


def test_successful_login_resets_failed_attempts(db_path):
    password = auth_store.ensure_account(TEST_EMAIL, db_path)

    auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)
    auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)
    assert auth_store.verify_login(TEST_EMAIL, password, db_path) is True

    with sqlite3.connect(db_path) as conn:
        failed_attempts = conn.execute(
            "SELECT failed_attempts FROM users WHERE id = 1"
        ).fetchone()[0]
    assert failed_attempts == 0


def test_ensure_account_rejects_blank_email(db_path):
    with pytest.raises(ValueError):
        auth_store.ensure_account("   ", db_path)


def test_verify_login_accepts_override_password_instead_of_generated_one(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)

    assert (
        auth_store.verify_login(
            TEST_EMAIL, "fixed-pass", db_path, override_password="fixed-pass"
        )
        is True
    )


def test_verify_login_rejects_generated_password_when_override_set(db_path):
    generated_password = auth_store.ensure_account(TEST_EMAIL, db_path)

    assert (
        auth_store.verify_login(
            TEST_EMAIL, generated_password, db_path, override_password="fixed-pass"
        )
        is False
    )


def test_create_session_returns_validatable_token(db_path):
    token = auth_store.create_session(db_path)

    assert token
    assert auth_store.validate_session(token, db_path) is True


def test_validate_session_rejects_unknown_token(db_path):
    assert auth_store.validate_session("does-not-exist", db_path) is False


def test_validate_session_rejects_blank_token(db_path):
    assert auth_store.validate_session("", db_path) is False
    assert auth_store.validate_session(None, db_path) is False


def test_invalidate_session_revokes_token(db_path):
    token = auth_store.create_session(db_path)
    auth_store.invalidate_session(token, db_path)

    assert auth_store.validate_session(token, db_path) is False


def test_invalidate_session_is_noop_for_unknown_token(db_path):
    # Must not raise even when the token was never issued.
    auth_store.invalidate_session("never-issued", db_path)


def test_sessions_have_no_expiry_and_stay_valid_over_time(db_path, monkeypatch):
    fake_now = [1_000_000.0]
    monkeypatch.setattr(auth_store.time, "time", lambda: fake_now[0])

    token = auth_store.create_session(db_path)
    fake_now[0] += 60 * 60 * 24 * 365  # one year later, no TTL enforced

    assert auth_store.validate_session(token, db_path) is True


def test_lockout_status_reports_full_attempts_before_any_failure(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)

    status = auth_store.get_lockout_status(TEST_EMAIL, db_path)

    assert status["locked"] is False
    assert status["attempts_remaining"] == auth_store.LOCKOUT_THRESHOLD
    assert status["seconds_remaining"] == 0


def test_lockout_status_counts_down_remaining_attempts(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)
    auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)
    auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)

    status = auth_store.get_lockout_status(TEST_EMAIL, db_path)

    assert status["locked"] is False
    assert status["attempts_remaining"] == auth_store.LOCKOUT_THRESHOLD - 2


def test_lockout_status_reports_locked_with_seconds_remaining(db_path, monkeypatch):
    auth_store.ensure_account(TEST_EMAIL, db_path)
    fake_now = [1_000_000.0]
    monkeypatch.setattr(auth_store.time, "time", lambda: fake_now[0])

    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)

    status = auth_store.get_lockout_status(TEST_EMAIL, db_path)

    assert status["locked"] is True
    assert status["attempts_remaining"] == 0
    assert 0 < status["seconds_remaining"] <= auth_store.LOCKOUT_SECONDS


def test_lockout_status_does_not_leak_real_account_state_for_wrong_email(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)
    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        auth_store.verify_login(TEST_EMAIL, "wrong-password", db_path)

    # A different email must not reveal that the real account is locked.
    status = auth_store.get_lockout_status("someone-else@example.com", db_path)

    assert status["locked"] is False
    assert status["attempts_remaining"] == auth_store.LOCKOUT_THRESHOLD
    assert status["seconds_remaining"] == 0


def test_lockout_status_for_missing_account_is_neutral(db_path):
    status = auth_store.get_lockout_status(TEST_EMAIL, db_path)

    assert status["locked"] is False
    assert status["attempts_remaining"] == auth_store.LOCKOUT_THRESHOLD
    assert status["seconds_remaining"] == 0


def test_verify_login_still_locks_out_with_override_password(db_path):
    auth_store.ensure_account(TEST_EMAIL, db_path)

    for _ in range(auth_store.LOCKOUT_THRESHOLD):
        assert (
            auth_store.verify_login(
                TEST_EMAIL, "wrong", db_path, override_password="fixed-pass"
            )
            is False
        )

    assert (
        auth_store.verify_login(
            TEST_EMAIL, "fixed-pass", db_path, override_password="fixed-pass"
        )
        is False
    )
