"""Shared fixtures for the API, CLI and UI suites.

Settings come from environment variables. Their defaults are in
tests/test.env (the public demo user from config/users.example.json); any
variable already set in your environment wins over that file:

    MSG_URL        server under test
    MSG_SERVER_START_TIMEOUT  seconds to wait for the server after a (re)start
    MSG_CA_FILE    certificate the tests trust
    MSG_USER, MSG_PASSWORD, MSG_TOKEN    credentials the tests log in with
    USERS_FILE     users file for a server the tests start themselves
    MSG_DB_PATH, MSG_AUDIT_LOG           host files some tests inspect

The unit tests use none of this.
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.parse
import uuid
import warnings
from pathlib import Path

import allure
import httpx
import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Defaults for the settings below; variables already set in the environment win.
load_dotenv(PROJECT_ROOT / "tests" / "test.env", override=False)


def _setting(name: str) -> str:
    """A setting from the environment (defaults in tests/test.env)."""
    return os.environ[name]


def _path_setting(name: str) -> Path:
    """A file path setting; relative paths are relative to the project root."""
    return PROJECT_ROOT / _setting(name)   # an absolute value replaces PROJECT_ROOT

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




def pytest_collection_modifyitems(config, items):
    """Retry failed API, CLI and UI tests when MSG_TEST_RETRY=true (see tests/test.env).

    Uses pytest-rerunfailures' `flaky` marker. Unit tests are never retried: they're
    deterministic, so a retry could only hide a real bug.
    """
    if os.environ.get("MSG_TEST_RETRY", "false").strip().lower() != "true":
        return
    reruns = int(os.environ.get("MSG_TEST_RETRY_COUNT", "0"))
    for item in items:
        if reruns > 0 and not item.get_closest_marker("unit"):
            item.add_marker(pytest.mark.flaky(reruns=reruns, reruns_delay=1))

def _layer(item: pytest.Item) -> str:
    """Which part of the system a test checks, from its marker (and file, for the CLI)."""
    if item.get_closest_marker("unit"):
        return "Unit"
    if item.get_closest_marker("ui"):
        return "UI"
    return "CLI" if item.path.name == "test_cli.py" else "API"


@pytest.fixture(autouse=True)
def _allure_layer(request):
    """Label every test with its layer in the Allure report: Unit, API, CLI or UI.

    Groups the report's tree by layer and feeds Allure's "durations by layer" chart.
    Without an Allure results folder, these calls do nothing.
    """
    layer = _layer(request.node)
    allure.dynamic.label("layer", layer)
    allure.dynamic.parent_suite(layer)

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Attach each test's captured logs and output to the Allure report, named after the test.

    Allure's own automatic attachments are switched off (--allure-no-capture in
    noxfile.py) because they're all called just "log" / "stdout". Empty phases
    attach nothing. Without an Allure results folder, allure.attach does nothing.
    """
    outcome = yield
    report = outcome.get_result()
    # pytest keeps each phase's output as sections titled e.g. "Captured log call";
    # later phases repeat earlier ones, so take only this phase's own sections.
    for title, text in report.sections:
        prefix = "Captured "
        if title.startswith(prefix) and title.endswith(f" {report.when}") and text:
            kind = title[len(prefix):].split()[0]          # "log", "stdout" or "stderr"
            allure.attach(text, name=f"{item.name} - {kind} ({report.when})",
                          attachment_type=allure.attachment_type.TEXT)


def _is_listening(url: str) -> bool:
    """True if something already accepts connections on the URL's host and port."""
    parts = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port or 443), timeout=2):
            return True
    except OSError:
        return False


def _check_it_is_our_server(url: str, ca_file: str) -> None:
    """Something listens on the URL: make sure it's this project's server.

    It must answer /healthz over TLS with the certificate in ca_file. Otherwise
    it's probably a server from another folder (different certificate) or an
    unrelated program, and testing it would only give confusing failures.
    """
    if not Path(ca_file).is_file():
        pytest.exit(f"A server is running on {url}, but there is no certificate at {ca_file} "
                    "to trust it. Run `docker compose down` and let the tests start their own "
                    "server, or set MSG_CA_FILE to that server's certificate.", returncode=1)
    try:
        response = httpx.get(f"{url}/healthz", verify=ssl.create_default_context(cafile=ca_file), timeout=5)
    except httpx.ConnectError as exc:
        if "CERTIFICATE_VERIFY_FAILED" in str(exc):
            pytest.exit(f"A server is running on {url}, but its certificate doesn't match {ca_file}. "
                        "It's probably from another folder: run `docker compose down` there, "
                        "or set MSG_CA_FILE to its certificate.", returncode=1)
        pytest.exit(f"Something is using {url} but isn't this service ({exc}).", returncode=1)
    except httpx.HTTPError as exc:
        pytest.exit(f"Something is using {url} but isn't this service ({exc}).", returncode=1)
    if response.status_code != 200:
        pytest.exit(f"Something is using {url} but isn't this service "
                    f"(/healthz returned {response.status_code}).", returncode=1)


def _wait_until_healthy(url: str, ca_file: str) -> None:
    timeout = float(_setting("MSG_SERVER_START_TIMEOUT"))
    context = ssl.create_default_context(cafile=ca_file)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/healthz", verify=context, timeout=3).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    pytest.exit(f"Server did not become healthy within {timeout:.0f}s", returncode=1)


@pytest.fixture(scope="session")
def server_url(ca_file: str):
    """The server's URL. Starts the server with Testcontainers if none is running.

    - Something already listening on the URL (e.g. your `docker compose up`):
      use it and leave it running.
    - Otherwise: create the certificate if it's missing, then build and start
      docker-compose.yml (users file: USERS_FILE), wait for
      /healthz, and stop it after the last test, even if tests fail.
    Only API/UI tests use this fixture, so unit test runs never start Docker.
    """
    url = _setting("MSG_URL").rstrip("/")
    if _is_listening(url):
        _check_it_is_our_server(url, ca_file)
        log.info("Using the server already running at %s", url)
        yield url
        return

    from testcontainers.compose import DockerCompose   # imported here: unit runs don't need it

    if not Path(ca_file).is_file():
        # Fresh machine: the server needs a certificate before it can start.
        log.info("No certificate at %s: creating one with scripts/gen_certs.py", ca_file)
        subprocess.run([sys.executable, str(PROJECT_ROOT / "scripts" / "gen_certs.py")], check=True)

    # wait=False: we wait for /healthz ourselves; compose --wait would trip over init exiting
    compose = DockerCompose(str(PROJECT_ROOT), build=True, wait=False)
    log.info("Starting the server with Testcontainers (docker compose up --build)")
    compose.start()
    try:
        _wait_until_healthy(url, ca_file)
        yield url
    finally:
        log.info("Stopping the server (docker compose down)")
        compose.stop()


@pytest.fixture(scope="session")
def token() -> str:
    return _setting("MSG_TOKEN")


@pytest.fixture(scope="session")
def username() -> str:
    return _setting("MSG_USER")


@pytest.fixture(scope="session")
def password() -> str:
    return _setting("MSG_PASSWORD")


@pytest.fixture(scope="session")
def ca_file() -> str:
    return str(_path_setting("MSG_CA_FILE"))


@pytest.fixture(scope="session")
def tls(ca_file: str) -> ssl.SSLContext:
    """TLS settings that trust only our self-signed certificate."""
    if not Path(ca_file).is_file():
        pytest.exit(f"CA file not found: {ca_file}. Run: python scripts/gen_certs.py", returncode=1)
    return ssl.create_default_context(cafile=ca_file)


@pytest.fixture(scope="session")
def db_path() -> Path:
    return _path_setting("MSG_DB_PATH")


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
            "The server rejected the API token (401). The credentials the tests use "
            "(MSG_USER, MSG_PASSWORD, MSG_TOKEN; defaults in tests/test.env) must exist in "
            "the users file the server loaded: USERS_FILE (config/users.example.json) when "
            "the tests start the server, or your config/users.json when you started it "
            "yourself. Check for leftover MSG_* variables in your shell.",
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
