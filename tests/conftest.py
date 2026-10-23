"""Shared fixtures for the API, CLI and UI suites.

These suites run against the server started with `docker compose up`.
Connection details come from environment variables, with defaults that match
config/users.example.json (see config/README.md):

    MSG_URL       https://localhost:8443
    MSG_TOKEN     alice's plain API token
    MSG_USER      alice
    MSG_PASSWORD  alice's plain password (web page, HTTP Basic)
    MSG_CA_FILE   certs/server.crt
    MSG_DB_PATH   data/messages.db (the SQLite file on the host volume)

The unit tests use none of this.
"""

from __future__ import annotations

import logging
import os
import ssl
import uuid
import warnings
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]

log = logging.getLogger("tests")


# ---------- logging: mark where each test starts and how it ended ----------
# HTTP calls are logged by httpx itself ("HTTP Request: POST ... 201 Created",
# method + URL + status only, never bodies). Settings are in pytest.ini.

def pytest_runtest_logstart(nodeid, location):
    log.info("START  %s", nodeid)


def pytest_runtest_logreport(report):
    # Log the result once: from the test body ("call"), or from setup/teardown
    # if that's where it failed or was skipped.
    if report.when == "call" or report.outcome != "passed":
        log.info("RESULT %s %s (%s)", report.outcome.upper(), report.nodeid, report.when)

# Demo credentials for config/users.example.json. Local use only.
_DEFAULT_TOKEN = "pRo1nGR3iigAbgNQbhmWgTHpc-4Yn_TF191Y_u53nZI"
_DEFAULT_PASSWORD = "changeme"


@pytest.fixture(scope="session")
def server_url() -> str:
    return os.environ.get("MSG_URL", "https://localhost:8443").rstrip("/")


@pytest.fixture(scope="session")
def token() -> str:
    return os.environ.get("MSG_TOKEN", _DEFAULT_TOKEN)


@pytest.fixture(scope="session")
def username() -> str:
    return os.environ.get("MSG_USER", "alice")


@pytest.fixture(scope="session")
def password() -> str:
    return os.environ.get("MSG_PASSWORD", _DEFAULT_PASSWORD)


@pytest.fixture(scope="session")
def ca_file() -> str:
    return os.environ.get("MSG_CA_FILE", str(PROJECT_ROOT / "certs" / "server.crt"))


@pytest.fixture(scope="session")
def tls(ca_file: str) -> ssl.SSLContext:
    """TLS settings that trust only our self-signed certificate."""
    if not Path(ca_file).is_file():
        pytest.exit(f"CA file not found: {ca_file}. Run: python scripts/gen_certs.py", returncode=1)
    return ssl.create_default_context(cafile=ca_file)


@pytest.fixture(scope="session")
def db_path() -> Path:
    return Path(os.environ.get("MSG_DB_PATH", PROJECT_ROOT / "data" / "messages.db"))


@pytest.fixture(scope="session")
def api(server_url: str, token: str, tls: ssl.SSLContext):
    """An authenticated HTTPS client, TLS pinned to the self-signed cert.

    Stops the whole run with one clear message if the cert is missing, the
    server isn't up, or the token isn't accepted, instead of failing every test.
    """
    client = httpx.Client(
        base_url=server_url,
        headers={"Authorization": f"Bearer {token}"},
        verify=tls,
        timeout=10.0,
    )
    try:
        client.get("/healthz").raise_for_status()
    except httpx.HTTPError as exc:
        pytest.exit(f"Server not reachable at {server_url} ({exc}). Run `docker compose up` first.", returncode=1)
    if client.get("/api/messages", params={"limit": 1}).status_code == 401:
        pytest.exit(
            "The server rejected the API token (401). MSG_TOKEN must match a user in "
            "config/users.json. Either set MSG_TOKEN, MSG_USER and MSG_PASSWORD to your "
            "user's values, or copy config/users.example.json to config/users.json and "
            "run `docker compose restart` to use the demo user.",
            returncode=1,
        )
    yield client
    client.close()


@pytest.fixture
def unique_tag() -> str:
    """A marker unique to one test, so tests never depend on each other's data."""
    return f"t-{uuid.uuid4().hex[:10]}"


@pytest.fixture
def created_ids(api: httpx.Client):
    """Collects ids of messages a test creates and deletes them afterwards."""
    ids: list[int] = []
    yield ids
    leftover: list[str] = []
    for message_id in ids:
        try:
            response = api.delete(f"/api/messages/{message_id}")
        except httpx.HTTPError as exc:          # timeout, dropped connection...
            leftover.append(f"{message_id} ({exc.__class__.__name__})")
            continue
        if response.status_code not in (204, 404):   # 404: the test already deleted it
            leftover.append(f"{message_id} (HTTP {response.status_code})")
    if leftover:
        warnings.warn(f"Test data not cleaned up: {', '.join(leftover)}")


@pytest.fixture
def create_message(api: httpx.Client, created_ids: list[int]):
    """Create a message through the API and register it for cleanup."""

    def _create(content: str) -> dict:
        response = api.post("/api/messages", json={"content": content})
        assert response.status_code == 201, response.text
        message = response.json()
        created_ids.append(message["id"])
        return message

    return _create
