"""CLI tests: run `python -m msgclient` as a subprocess, the way a script or CI
job would, against the running container. Requires `pip install -e ./client`.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

import pytest

from tests.sample_data import PLACEHOLDERS, RAW_VALUES, sensitive_message

pytestmark = pytest.mark.api

log = logging.getLogger("tests.cli")


@pytest.fixture
def run_cli(server_url, token, ca_file):
    """Run msgclient with the given args; returns the CompletedProcess."""

    def _run(*args: str, env_overrides: dict[str, str | None] | None = None):
        env = {**os.environ, "MSG_URL": server_url, "MSG_TOKEN": token, "MSG_CA_FILE": ca_file}
        for key, value in (env_overrides or {}).items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        result = subprocess.run(
            [sys.executable, "-m", "msgclient", *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        # Message text is left out of the log; only the command and its outcome.
        shown = "send <message>" if args and args[0] == "send" else " ".join(args)
        log.info("msgclient %s -> exit %s", shown, result.returncode)
        if result.returncode != 0:
            log.info("stderr: %s", result.stderr.strip())
        return result

    return _run


# Command:  msgclient send "<JWT, email, IPv4 and card>" --json
# Expected: exit code 0, valid JSON on stdout with all four placeholders, no raw values
def test_send_json_prints_redacted_message(run_cli, created_ids, unique_tag):
    result = run_cli("send", sensitive_message(unique_tag), "--json")
    assert result.returncode == 0, result.stderr

    message = json.loads(result.stdout)
    created_ids.append(message["id"])
    for placeholder in PLACEHOLDERS:
        assert placeholder in message["content"]
    for raw in RAW_VALUES:
        assert raw not in result.stdout


# Command:  msgclient list --limit 500 --json
# Expected: exit code 0, a JSON array that includes the message just created
def test_list_json_prints_array(run_cli, create_message, unique_tag):
    message = create_message(f"{unique_tag} listed")
    result = run_cli("list", "--limit", "500", "--json")
    assert result.returncode == 0, result.stderr

    messages = json.loads(result.stdout)
    assert isinstance(messages, list)
    assert message["id"] in [m["id"] for m in messages]


# Command:  msgclient get {id} --json, then msgclient delete {id}
# Expected: the message as JSON (exit 0), then "OK" (exit 0)
def test_get_and_delete(run_cli, create_message, unique_tag):
    message = create_message(f"{unique_tag} cli get/delete")

    got = run_cli("get", str(message["id"]), "--json")
    assert got.returncode == 0, got.stderr
    assert json.loads(got.stdout) == message

    deleted = run_cli("delete", str(message["id"]))
    assert deleted.returncode == 0, deleted.stderr
    assert deleted.stdout.strip() == "OK"


# Command:  msgclient get 999999999 --json
# Expected: exit code 1, "404" on stderr, stdout empty
def test_get_unknown_id_exits_1_with_error_on_stderr(run_cli):
    result = run_cli("get", "999999999", "--json")
    assert result.returncode == 1
    assert "404" in result.stderr
    assert result.stdout == ""          # stdout stays clean for scripts


# Command:  msgclient list   with MSG_TOKEN=not-a-real-token
# Expected: exit code 3, "Not authenticated" on stderr
def test_wrong_token_exits_3(run_cli):
    result = run_cli("list", env_overrides={"MSG_TOKEN": "not-a-real-token"})
    assert result.returncode == 3
    assert "Not authenticated" in result.stderr


# Command:  msgclient list   with MSG_URL unset, then with MSG_TOKEN unset
# Expected: exit code 2, "MSG_URL and MSG_TOKEN must be set" on stderr, each time
@pytest.mark.parametrize("missing", ["MSG_URL", "MSG_TOKEN"])
def test_missing_url_or_token_exits_2(run_cli, missing):
    result = run_cli("list", env_overrides={missing: None})
    assert result.returncode == 2
    assert "MSG_URL and MSG_TOKEN must be set" in result.stderr


# Command:  msgclient list   with MSG_CA_FILE=no/such/server.crt
# Expected: exit code 2, "CA file not found" on stderr, no Python traceback
def test_missing_ca_file_exits_2_with_clear_message(run_cli):
    result = run_cli("list", env_overrides={"MSG_CA_FILE": "no/such/server.crt"})
    assert result.returncode == 2
    assert "CA file not found" in result.stderr
    assert "Traceback" not in result.stderr
