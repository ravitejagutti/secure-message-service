"""API tests against the running container (docker compose up)."""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

import httpx
import pytest

from tests.sample_data import EMAIL, PLACEHOLDERS, RAW_VALUES, sensitive_message

pytestmark = pytest.mark.api

PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ---------- create / read ----------

# Request:  POST /api/messages {"content": "<tag> hello"}
# Expected: 201, body has the same content, author == "alice", redactions == {},
#           an integer id and a created_at timestamp
def test_create_message_returns_201_with_details(api, username, unique_tag, created_ids):
    response = api.post("/api/messages", json={"content": f"{unique_tag} hello"})
    assert response.status_code == 201
    body = response.json()
    created_ids.append(body["id"])

    assert body["content"] == f"{unique_tag} hello"
    assert body["author"] == username
    assert body["redactions"] == {}
    assert isinstance(body["id"], int)
    assert body["created_at"]


# Request:  POST /api/messages with {"content": ""} / {} / 10,001 chars / {"content": 123}
# Expected: 422 for each
@pytest.mark.parametrize(
    "payload",
    [{"content": ""}, {}, {"content": "x" * 10_001}, {"content": 123}],
    ids=["empty", "missing", "too-long", "not-a-string"],
)
def test_invalid_message_body_returns_422(api, payload):
    response = api.post("/api/messages", json=payload)
    assert response.status_code == 422


# Request:  POST /api/messages with "ravi@example.com" + 10,001 chars (too long)
# Expected: 422, and "ravi@example.com" does not appear anywhere in the response
def test_validation_error_does_not_echo_input(api):
    # Rejected content was never redacted, so it must not come back in the error.
    response = api.post("/api/messages", json={"content": f"{EMAIL} " + "x" * 10_001})
    assert response.status_code == 422
    assert EMAIL not in response.text


# Setup:    create "first", then "second"
# Request:  GET /api/messages?limit=500
# Expected: 200, "second" appears before "first"
def test_list_returns_newest_first(api, create_message, unique_tag):
    first = create_message(f"{unique_tag} first")
    second = create_message(f"{unique_tag} second")

    response = api.get("/api/messages", params={"limit": 500})
    assert response.status_code == 200
    ours = [m["id"] for m in response.json() if m["id"] in (first["id"], second["id"])]
    assert ours == [second["id"], first["id"]], (
        f"expected newest first: {second['id']} then {first['id']}, got {ours}"
    )


# Request:  GET /api/messages?limit=1&offset=0, then ?limit=1&offset=1
# Expected: one message each; page 1 has the higher (newer) id
def test_list_supports_limit_and_offset(api, create_message, unique_tag):
    create_message(f"{unique_tag} a")
    create_message(f"{unique_tag} b")

    page1 = api.get("/api/messages", params={"limit": 1, "offset": 0}).json()
    page2 = api.get("/api/messages", params={"limit": 1, "offset": 1}).json()
    assert len(page1) == 1 and len(page2) == 1
    assert page1[0]["id"] > page2[0]["id"]


# Request:  GET /api/messages?limit=0 / ?limit=501 / ?offset=-1
# Expected: 422 for each
@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 501}, {"offset": -1}])
def test_invalid_paging_params_return_422(api, params):
    assert api.get("/api/messages", params=params).status_code == 422


# Request:  GET /api/messages/{id} for a message just created
# Expected: 200, body identical to the create response
def test_get_message_by_id(api, create_message, unique_tag):
    message = create_message(f"{unique_tag} fetch me")
    response = api.get(f"/api/messages/{message['id']}")
    assert response.status_code == 200
    assert response.json() == message


# Request:  GET /api/messages/999999999
# Expected: 404, {"detail": "Message not found"}
def test_get_unknown_id_returns_404(api):
    response = api.get("/api/messages/999999999")
    assert response.status_code == 404
    assert response.json() == {"detail": "Message not found"}


# ---------- redaction through the API ----------

# Request:  POST a message containing a JWT, email, IPv4 and card; then GET it
# Expected: both responses contain all four placeholders and none of the raw values,
#           redactions == {"JWT": 1, "EMAIL": 1, "IPV4": 1, "CREDIT_CARD": 1}
def test_sensitive_data_is_redacted_in_api_responses(api, create_message, unique_tag):
    created = create_message(sensitive_message(unique_tag))

    for body in (created, api.get(f"/api/messages/{created['id']}").json()):
        for placeholder in PLACEHOLDERS:
            assert placeholder in body["content"]
        for raw in RAW_VALUES:
            assert raw not in body["content"]
        assert body["redactions"] == {"JWT": 1, "EMAIL": 1, "IPV4": 1, "CREDIT_CARD": 1}


# Request:  POST a message containing a JWT, email, IPv4 and card
# Check:    read data/messages.db directly with sqlite3, bypassing the API
# Expected: the stored content has no raw values and equals the API response content
def test_raw_values_never_reach_the_database(create_message, unique_tag, db_path):
    created = create_message(sensitive_message(unique_tag))
    # Fail, never skip: if this check can't run, the suite must not go green.
    assert db_path.is_file(), (
        f"Database file not found at {db_path}. Check the ./data volume, or set MSG_DB_PATH."
    )

    # Read the SQLite file on the host volume directly, bypassing the API.
    conn = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        (stored,) = conn.execute(
            "SELECT content FROM messages WHERE id = ?", (created["id"],)
        ).fetchone()
    finally:
        conn.close()
    for raw in RAW_VALUES:
        assert raw not in stored
    assert stored == created["content"]


# ---------- delete ----------

# Request:  DELETE /api/messages/{id}
# Expected: 204 with an empty body; then GET returns 404 and the list no longer has it
def test_delete_removes_message(api, create_message, unique_tag):
    message = create_message(f"{unique_tag} delete me")

    response = api.delete(f"/api/messages/{message['id']}")
    assert response.status_code == 204
    assert response.content == b""

    assert api.get(f"/api/messages/{message['id']}").status_code == 404
    listed_ids = [m["id"] for m in api.get("/api/messages", params={"limit": 500}).json()]
    assert message["id"] not in listed_ids


# Request:  DELETE the same id twice, then DELETE /api/messages/999999999
# Expected: 204, then 404, then 404
def test_delete_unknown_or_already_deleted_returns_404(api, create_message, unique_tag):
    message = create_message(f"{unique_tag} delete twice")
    assert api.delete(f"/api/messages/{message['id']}").status_code == 204
    assert api.delete(f"/api/messages/{message['id']}").status_code == 404
    assert api.delete("/api/messages/999999999").status_code == 404


# ---------- authentication ----------

API_ROUTES = [
    ("POST", "/api/messages"),
    ("GET", "/api/messages"),
    ("GET", "/api/messages/1"),
    ("DELETE", "/api/messages/1"),
]


# Request:  POST, GET, GET {id}, DELETE {id} with no Authorization header
# Expected: 401, {"detail": "Not authenticated"} on every route
@pytest.mark.parametrize("method, path", API_ROUTES)
def test_api_routes_reject_missing_token(server_url, tls, method, path):
    with httpx.Client(base_url=server_url, verify=tls) as anon:
        response = anon.request(method, path, json={"content": "x"} if method == "POST" else None)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


# Request:  same four routes with "Authorization: Bearer not-a-real-token"
# Expected: 401, {"detail": "Not authenticated"} on every route
@pytest.mark.parametrize("method, path", API_ROUTES)
def test_api_routes_reject_wrong_token(server_url, tls, method, path):
    headers = {"Authorization": "Bearer not-a-real-token"}
    with httpx.Client(base_url=server_url, verify=tls, headers=headers) as bad:
        response = bad.request(method, path, json={"content": "x"} if method == "POST" else None)
    assert response.status_code == 401
    assert response.json() == {"detail": "Not authenticated"}


# Request:  GET / with no login / wrong password / unknown user / correct login
# Expected: 401 + "WWW-Authenticate: Basic" for the first three; 200 HTML for the last
def test_web_page_requires_basic_auth(server_url, tls, username, password):
    with httpx.Client(base_url=server_url, verify=tls) as browser_like:
        no_creds = browser_like.get("/")
        wrong = browser_like.get("/", auth=(username, "wrong-password"))
        unknown_user = browser_like.get("/", auth=("nobody", password))
        ok = browser_like.get("/", auth=(username, password))

    for response in (no_creds, wrong, unknown_user):
        assert response.status_code == 401
        assert response.headers["www-authenticate"].lower().startswith("basic")
    assert ok.status_code == 200
    assert "text/html" in ok.headers["content-type"]


# Request:  GET / with "Authorization: Bearer <token>"
# Expected: 401 (the page accepts only username + password)
def test_api_token_does_not_open_the_web_page(server_url, tls, token):
    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=server_url, verify=tls, headers=headers) as client:
        assert client.get("/").status_code == 401


# Request:  GET /healthz with no login
# Expected: 200, {"status": "ok"}
def test_health_check_needs_no_credentials(server_url, tls):
    with httpx.Client(base_url=server_url, verify=tls) as anon:
        response = anon.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


# ---------- TLS ----------

# Request:  GET http://localhost:8443/healthz (plain HTTP, no TLS)
# Expected: the request fails; no successful response
def test_plain_http_is_not_served(server_url):
    plain_url = server_url.replace("https://", "http://", 1)
    with pytest.raises(httpx.HTTPError):
        response = httpx.get(f"{plain_url}/healthz", timeout=5.0)
        # Some stacks answer garbage with an error status instead of dropping
        # the connection; either way, no successful plain-HTTP response.
        response.raise_for_status()


# Request:  GET /healthz trusting only the system CA store, then trusting certs/server.crt
# Expected: first fails with a certificate error, second returns 200
def test_self_signed_cert_is_trusted_only_when_pinned(server_url, tls):
    # Trusting only the system CA store fails: the cert is self-signed...
    with pytest.raises(httpx.ConnectError):
        httpx.get(f"{server_url}/healthz", verify=True, timeout=5.0)
    # ...while pinning our own cert succeeds.
    assert httpx.get(f"{server_url}/healthz", verify=tls, timeout=5.0).status_code == 200


# ---------- persistence ----------

# Setup:    create a message, run "docker compose restart", wait for /healthz
# Expected: GET /api/messages/{id} returns 200 with the same message
@pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available")
def test_message_survives_container_restart(api, create_message, unique_tag):
    message = create_message(f"{unique_tag} survive restart")

    subprocess.run(
        ["docker", "compose", "restart"], cwd=PROJECT_ROOT, check=True, capture_output=True
    )
    _wait_until_healthy(api)

    response = api.get(f"/api/messages/{message['id']}")
    assert response.status_code == 200
    assert response.json() == message


# Setup:    create a message (with sensitive data), delete it, then call the API with a wrong token
# Check:    read the audit log file on the host volume (logs/audit.log)
# Expected: lines for message.created, message.deleted (with who deleted it) and auth.failed;
#           the message text and raw values never appear in the log
def test_audit_log_records_events_without_content(api, server_url, tls, username, unique_tag):
    audit_log = Path(os.environ.get("MSG_AUDIT_LOG", PROJECT_ROOT / "logs" / "audit.log"))

    response = api.post("/api/messages", json={"content": sensitive_message(unique_tag)})
    assert response.status_code == 201
    message_id = response.json()["id"]
    assert api.delete(f"/api/messages/{message_id}").status_code == 204
    with httpx.Client(base_url=server_url, verify=tls,
                      headers={"Authorization": "Bearer not-a-real-token"}) as bad:
        assert bad.get("/api/messages").status_code == 401

    expected = [
        f"AUDIT message.created id={message_id} by={username} redactions=",
        f"AUDIT message.deleted id={message_id} by={username}",
        "AUDIT auth.failed route=/api/messages",
    ]
    logs = ""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        logs = audit_log.read_text(encoding="utf-8") if audit_log.is_file() else ""
        if all(line in logs for line in expected):
            break
        time.sleep(0.5)

    assert audit_log.is_file(), f"Audit log not found at {audit_log}. Check the ./logs volume, or set MSG_AUDIT_LOG."
    for line in expected:
        assert line in logs, f"missing from audit log: {line}"
    assert unique_tag not in logs                  # message text is never logged
    for raw in RAW_VALUES:
        assert raw not in logs


def _wait_until_healthy(api: httpx.Client, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if api.get("/healthz").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    pytest.fail("Server did not come back after restart")
