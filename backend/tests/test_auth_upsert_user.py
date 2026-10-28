"""Tests for app/auth.py's _upsert_user — runs on every authenticated
request via get_current_user. The 2026-09-21 fix: skip the UPDATE+commit
entirely when nothing about the user actually changed, since that write
was previously unconditional and, under concurrent requests, serialized
otherwise-independent reads on Postgres row-level locking for the same
user row (see the function's own docstring for the full story).
"""

from __future__ import annotations

from sqlalchemy.orm import sessionmaker

from app.auth import _upsert_user
from app.models.user import User
from tests.db import fresh_engine


def _db():
    engine = fresh_engine()
    return sessionmaker(bind=engine, future=True)()


def _count_commits(db, monkeypatch) -> list[int]:
    calls = [0]
    real_commit = db.commit

    def _counted_commit():
        calls[0] += 1
        real_commit()

    monkeypatch.setattr(db, "commit", _counted_commit)
    return calls


def test_creates_a_new_user_and_commits(monkeypatch):
    db = _db()
    calls = _count_commits(db, monkeypatch)

    user = _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    assert user.username == "alice"
    assert calls[0] == 1
    assert db.query(User).filter(User.oidc_subject == "sub-1").count() == 1


def test_unchanged_fields_do_not_trigger_a_write(monkeypatch):
    db = _db()
    _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    calls = _count_commits(db, monkeypatch)
    user = _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    assert user.username == "alice"
    assert calls[0] == 0  # the whole point of the fix


def test_changed_field_still_triggers_exactly_one_write(monkeypatch):
    db = _db()
    _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    calls = _count_commits(db, monkeypatch)
    user = _upsert_user(db, "sub-1", username="alice", email="alice@example.org", is_admin=False)

    assert user.email == "alice@example.org"
    assert calls[0] == 1


def test_the_username_stays_kodex_s_after_the_account_is_made(monkeypatch):
    db = _db()
    _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    calls = _count_commits(db, monkeypatch)
    user = _upsert_user(db, "sub-1", username="alice-renamed", email="alice@example.com", is_admin=False)

    assert user.username == "alice"
    assert calls[0] == 0


def test_no_account_is_made_when_creating_is_off():
    db = _db()
    assert _upsert_user(db, "sub-1", username="alice", email=None, is_admin=False, create=False) is None
    assert db.query(User).count() == 0


def test_admin_promotion_is_detected_as_a_change(monkeypatch):
    db = _db()
    _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=False)

    calls = _count_commits(db, monkeypatch)
    user = _upsert_user(db, "sub-1", username="alice", email="alice@example.com", is_admin=True)

    assert user.is_admin is True
    assert calls[0] == 1
