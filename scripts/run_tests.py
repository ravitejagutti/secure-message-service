"""Run the test suites with one command.

    python scripts/run_tests.py              # all suites
    python scripts/run_tests.py unit         # redaction unit tests only (no server needed)
    python scripts/run_tests.py api          # API + CLI tests
    python scripts/run_tests.py ui           # Playwright tests
    python scripts/run_tests.py --install    # fresh machine / CI: set up everything first
    python scripts/run_tests.py api -k delete   # anything extra goes to pytest

--install: install test dependencies and Chromium, and create the self-signed
cert if it doesn't exist yet. (Test setup only; creating config/users.json for
running the app is a separate step, see the README.)

Steps: (optional) install -> for "all": unit tests first, stopping here if any
fail (fast feedback, no server needed) -> for api/ui/all: check the cert, start
the server, wait for /healthz -> pytest -> stop the server -> print the report
paths. Reports are timestamped so earlier runs are kept:
reports/<suite>_<YYYY-MM-DD_HH-MM-SS>.html and .log (a full run writes
all-unit_... and all-integration_...).

Server lifecycle: if this script started the server, it always stops it at the
end (`docker compose down`), even when tests fail or the run is interrupted.
If a server is already running, the script refuses to start its own and points
you to --no-build, which tests the running server and leaves it as is.
Data in ./data is kept either way.

Test credentials, from environment variables:
  - MSG_USER, MSG_PASSWORD and MSG_TOKEN all set: the server uses your
    config/users.json and the tests log in with those values.
  - otherwise (none, or only some, e.g. a MSG_TOKEN left over from msgclient):
    they are ignored, the server uses config/users.example.json and the tests
    use the demo user (defaults in tests/conftest.py).
With --no-build, the tests use MSG_* (or the demo defaults) against the running server.
"""

from __future__ import annotations

import argparse
import os
import socket
import ssl
import subprocess
import sys
import time
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Suites you can name as the first argument. "all" runs unit tests first, then
# (only if they pass) starts the server and runs the API, CLI and UI tests.
SUITES = ("all", "unit", "api", "ui")

CREDENTIAL_VARS = ("MSG_USER", "MSG_PASSWORD", "MSG_TOKEN")
DEMO_USERS_FILE = "config/users.example.json"   # matches the defaults in tests/conftest.py


def run(cmd: list[str], env: dict[str, str] | None = None, check: bool = True) -> None:
    print(f"\n>>> {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=ROOT, check=check, env=env)


def bootstrap() -> None:
    """Fresh machine / CI: test dependencies, browser and cert."""
    run([sys.executable, "-m", "pip", "install", "-r", "requirements-dev.txt"])
    browser_cmd = [sys.executable, "-m", "playwright", "install", "chromium"]
    if sys.platform.startswith("linux"):
        browser_cmd.insert(-1, "--with-deps")    # system libraries Chromium needs on Linux
    run(browser_cmd)

    if not (ROOT / "certs" / "server.crt").is_file():
        run([sys.executable, "scripts/gen_certs.py"])


def use_own_credentials() -> bool:
    """True only if all three credential variables are set.

    The three are treated as a set: a partial set (e.g. just MSG_TOKEN, left over
    from using msgclient) is ignored with a note, and the demo user is used.
    Mixing your values with demo ones would make some logins pass and others fail.
    """
    present = [name for name in CREDENTIAL_VARS if os.environ.get(name)]
    if present and len(present) < len(CREDENTIAL_VARS):
        print(
            f"\n>>> note: only {', '.join(present)} set; ignoring it and using the demo user "
            f"(set all of {', '.join(CREDENTIAL_VARS)} to use your own)"
        )
    return len(present) == len(CREDENTIAL_VARS)


def check_setup() -> None:
    if not (ROOT / "certs" / "server.crt").is_file():
        sys.exit(
            "Setup incomplete: certs/server.crt is missing.\n"
            "  Run: python scripts/gen_certs.py   (or run this script with --install)"
        )


def ensure_no_server_running(url: str) -> None:
    """Refuse to start a test server if something already listens on the port.

    A server you started yourself (or any other program on that port) is never
    restarted or stopped behind your back: test it with --no-build instead.
    """
    parts = urllib.parse.urlsplit(url)
    host, port = parts.hostname or "localhost", parts.port or 443
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except OSError:
        return                                   # nothing listening: safe to start
    sys.exit(
        f"A server is already running on {host}:{port}.\n"
        "  To test it as is:      python scripts/run_tests.py --no-build   (add a suite name first if needed)\n"
        "  To let this script start (and later stop) its own: run `docker compose down` first."
    )


def wait_until_healthy(url: str, ca_file: Path, timeout: float = 60.0) -> None:
    context = ssl.create_default_context(cafile=str(ca_file))
    deadline = time.monotonic() + timeout
    print(f"\n>>> waiting for {url}/healthz", end="", flush=True)
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", context=context, timeout=3) as r:
                if r.status == 200:
                    print(" ready", flush=True)
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            pass
        print(".", end="", flush=True)
        time.sleep(1)
    sys.exit(f"\nServer did not become healthy within {timeout:.0f}s. Check: docker compose logs")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--install", action="store_true", help="set up a fresh machine first (test deps, browser, cert)")
    parser.add_argument("--no-build", action="store_true", help="use the already-running server as is")
    # The suite is the first word if it is one of SUITES; everything else that
    # isn't --install / --no-build goes to pytest unchanged (e.g. -k "not restart").
    argv = sys.argv[1:]
    suite = argv.pop(0) if argv and argv[0] in SUITES else "all"
    args, pytest_args = parser.parse_known_args(argv)
    args.suite = suite

    if args.install:
        bootstrap()

    # pytest exit codes: 0 = all passed, 5 = no test matched the filters (e.g. -k).
    # Both count as "nothing failed"; anything else is a failure.
    OK = (0, 5)

    # Timestamped names keep every run's results, e.g. reports/api_2026-10-22_21-30-05.html
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    reports: list[tuple[Path, Path]] = []
    started_server = False
    test_env = os.environ.copy()

    def run_pytest(marker: str, name: str) -> int:
        report = ROOT / "reports" / f"{name}_{stamp}.html"
        log_file = ROOT / "reports" / f"{name}_{stamp}.log"
        reports.append((report, log_file))
        cmd = [sys.executable, "-m", "pytest", f"--html={report}", f"--log-file={log_file}",
               "-m", marker, *pytest_args]
        print(f"\n>>> {' '.join(cmd[1:])}", flush=True)
        return subprocess.run(cmd, cwd=ROOT, env=test_env).returncode

    try:
        if args.suite == "unit":
            code = run_pytest("unit", "unit")
        else:
            unit_code = None
            if args.suite == "all":
                # Fast feedback: unit tests first (no server, ~1 s). If one fails,
                # stop before building the server and running the slow suites.
                unit_code = run_pytest("unit", "all-unit")
                if unit_code not in OK:
                    print("\n>>> unit tests failed: skipping the server and the API/UI tests")

            if unit_code is None or unit_code in OK:
                own_credentials = use_own_credentials()
                if not own_credentials:
                    # Make sure the tests use the demo defaults, not a partial leftover set.
                    for name in CREDENTIAL_VARS:
                        test_env.pop(name, None)
                check_setup()
                url = os.environ.get("MSG_URL", "https://localhost:8443").rstrip("/")
                ca_file = Path(os.environ.get("MSG_CA_FILE", ROOT / "certs" / "server.crt"))
                if not args.no_build:
                    ensure_no_server_running(url)    # never touch a server you started yourself
                    compose_env = os.environ.copy()
                    if own_credentials:
                        print("\n>>> using MSG_USER / MSG_PASSWORD / MSG_TOKEN with config/users.json")
                    else:
                        print(f"\n>>> using the demo user ({DEMO_USERS_FILE})")
                        compose_env["USERS_FILE"] = DEMO_USERS_FILE
                    # --force-recreate: the server reads the users file only at startup.
                    started_server = True            # set first: tear down even if startup fails
                    run(["docker", "compose", "up", "--build", "--force-recreate", "-d"], env=compose_env)
                wait_until_healthy(url, ca_file)

                if args.suite == "all":
                    integration_code = run_pytest("api or ui", "all-integration")
                    # The run fails if either part failed; "nothing matched" only if both did.
                    failed = [c for c in (unit_code, integration_code) if c not in OK]
                    code = failed[0] if failed else (5 if unit_code == integration_code == 5 else 0)
                else:
                    code = run_pytest(args.suite, args.suite)
            else:
                code = unit_code
    finally:
        # Started by this script -> stopped by this script, whatever happened above
        # (tests failed, server never became healthy, Ctrl+C). Data in ./data is kept.
        if started_server:
            run(["docker", "compose", "down"], check=False)

    for report, log_file in reports:
        print(f"\nHTML report: {report}")
        print(f"Run log:     {log_file}")
    return code

if __name__ == "__main__":
    sys.exit(main())
