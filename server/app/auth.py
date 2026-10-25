"""User store, Bearer (API) and Basic (browser page) auth dependencies.

Passwords are hashed with bcrypt and checked via bcrypt.checkpw -- deliberately
slow, to resist offline brute-forcing of human-chosen passwords. API tokens are
long random strings, not human-chosen, so they're hashed with SHA-256 and
compared with hmac.compare_digest -- a fast hash is fine there because the
token's entropy, not the hash speed, is what resists guessing.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from pathlib import Path

import bcrypt
from fastapi import Depends, HTTPException, Request
from fastapi.security import (
    HTTPAuthorizationCredentials,
    HTTPBasic,
    HTTPBasicCredentials,
    HTTPBearer,
)

from .audit import audit

_basic_security = HTTPBasic(realm="Secure Message Service")
_bearer_security = HTTPBearer(auto_error=False)
_DUMMY_HASH = bcrypt.hashpw(b"placeholder", bcrypt.gensalt(rounds=12))


@dataclass(frozen=True)
class User:
    username: str
    password_bcrypt: str
    api_token_sha256: str


class UserStore:
    """The preloaded users, reloaded automatically when the users file changes.

    Before each login check, the file's modification time is compared with the
    last load (one cheap filesystem call); if it changed, the file is read again.
    So adding, changing or removing a user (e.g. with scripts/make_user.py) takes
    effect on the next request, without restarting the server.
    """

    def __init__(self, users: list[User], path: str | None = None):
        self._users = users
        self._path = Path(path) if path else None
        self._mtime = self._path.stat().st_mtime_ns if self._path else None

    @staticmethod
    def _read(path: Path) -> list[User]:
        raw = json.loads(path.read_text())
        return [User(u["username"], u["password_bcrypt"], u["api_token_sha256"]) for u in raw]

    @classmethod
    def load(cls, path: str) -> "UserStore":
        return cls(cls._read(Path(path)), path)

    def _current_users(self) -> list[User]:
        """The users, re-read first if the file changed since the last load."""
        if self._path is not None:
            mtime = self._path.stat().st_mtime_ns
            if mtime != self._mtime:
                self._users = self._read(self._path)
                self._mtime = mtime
        return self._users

    def find_by_token(self, token: str) -> User | None:
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        for user in self._current_users():
            if hmac.compare_digest(user.api_token_sha256, token_hash):
                return user
        return None

    def verify_password(self, username: str, password: str) -> bool:
        for user in self._current_users():
            if user.username == username:
                return bcrypt.checkpw(password.encode(), user.password_bcrypt.encode())
        # No such user: still run bcrypt so a missing-username response takes
        # roughly as long as a wrong-password one (no user enumeration via timing).
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        return False


def require_bearer_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_security),
) -> str:
    
    """Dependency for /api/* routes. 401 on any missing/invalid token,
    with no detail that would let a caller distinguish the two cases."""

    if credentials is None:
        _audit_auth_failure(request, "missing_token")
        raise HTTPException(status_code=401, detail="Not authenticated")

    user_store: UserStore = request.app.state.user_store
    user = user_store.find_by_token(credentials.credentials)
    if user is None:
        _audit_auth_failure(request, "invalid_token")
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user.username


def require_basic_auth(
    request: Request,
    credentials: HTTPBasicCredentials = Depends(_basic_security),
) -> str:
    
    """Dependency for the server-rendered page. HTTPBasic already returns
    401 + WWW-Authenticate when the header is missing; this adds the same
    response when credentials are present but wrong."""

    user_store: UserStore = request.app.state.user_store
    if not user_store.verify_password(credentials.username, credentials.password):
        # The attempted username is not logged: people sometimes type a password there.
        _audit_auth_failure(request, "invalid_password")
        raise HTTPException(
            status_code=401,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def _audit_auth_failure(request: Request, reason: str) -> None:
    ip = request.client.host if request.client else "unknown"
    audit("auth.failed", route=request.url.path, ip=ip, reason=reason)
