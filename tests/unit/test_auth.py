"""Unit tests for the user store: users file changes are picked up without a restart."""

from __future__ import annotations

import hashlib
import json
import os

import bcrypt
import pytest

from server.app.auth import UserStore

pytestmark = pytest.mark.unit


def _user(name: str, password: str, token: str) -> dict:
    return {
        "username": name,
        "password_bcrypt": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode(),
        "api_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


def _write(path, users: list[dict], bump_seconds: int = 0) -> None:
    path.write_text(json.dumps(users))
    if bump_seconds:                      # make sure the modification time visibly changes
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + bump_seconds * 1_000_000_000))


# Setup:    users file with alice; load it
# Action:   rewrite the file with bob instead of alice (no reload call, no restart)
# Expected: bob's token and password work; alice's token no longer does
def test_users_file_changes_are_picked_up_without_restart(tmp_path):
    users_file = tmp_path / "users.json"
    _write(users_file, [_user("alice", "alice-pw", "alice-token")])
    store = UserStore.load(str(users_file))
    assert store.find_by_token("alice-token").username == "alice"

    _write(users_file, [_user("bob", "bob-pw", "bob-token")], bump_seconds=1)

    assert store.find_by_token("bob-token").username == "bob"
    assert store.verify_password("bob", "bob-pw")
    assert store.find_by_token("alice-token") is None


# Setup:    users file with alice; load it
# Action:   look her up several times without touching the file
# Expected: same answer each time (the file is only re-read when it changes)
def test_unchanged_users_file_keeps_working(tmp_path):
    users_file = tmp_path / "users.json"
    _write(users_file, [_user("alice", "alice-pw", "alice-token")])
    store = UserStore.load(str(users_file))
    for _ in range(3):
        assert store.find_by_token("alice-token").username == "alice"
        assert store.verify_password("alice", "alice-pw")
    assert not store.verify_password("alice", "wrong")
