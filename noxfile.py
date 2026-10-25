"""Test sessions, run with nox: each session gets its own clean virtual environment.

    nox                          # unit, then integration; stops if unit fails (fast feedback)
    nox -s unit                  # unit tests only (no server)
    nox -s integration           # API + CLI + UI tests: in parallel, then the serial ones
    nox -s api                   # API + CLI tests only (one after another)
    nox -s ui                    # Playwright tests only (one after another)
    nox -s unit -- -k email      # anything after -- goes to pytest

Server for `integration`: nox starts it before pytest and stops it afterwards
(even if tests fail), unless one is already running on MSG_URL, which is then
used and left running. All test workers share that one server. For `api` and
`ui`, the test fixture in tests/conftest.py starts and stops it instead.

Reports: each nox run gets its own folder, reports/<YYYY-MM-DD_HH-MM-SS>/, so
earlier runs are kept. Every pytest run of that nox run writes into it:
allure-results/ (shared, so one report covers all of them), <name>.log (a text
log per pytest run), and playwright/ (traces and screenshots of failed UI
tests). After each session, nox builds ONE Allure
report for the run so far: reports/<time>/allure-report/index.html, a single
self-contained HTML file. Needs the Allure 3 CLI (npm install -g allure);
without it, the Allure report is skipped with a note.
"""

import os
import shutil
import socket
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import nox

# Plain `nox` runs these, in this order, and stops at the first failing one.
nox.options.sessions = ["unit", "integration"]
nox.options.stop_on_first_error = True

ROOT = Path(__file__).resolve().parent

# One folder per nox run, named by its start time; earlier runs are kept.
RUN_DIR = ROOT / "reports" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

# pytest exit codes that count as "nothing failed": 0 = passed, 5 = no test matched (e.g. -k)
OK_CODES = [0, 5]

# Shared by every pytest run of this nox run, so one Allure report covers them all.
ALLURE_RESULTS = RUN_DIR / "allure-results"
ALLURE_REPORT = RUN_DIR / "allure-report"

# Wall-clock time of each part of this nox run, shown in the Allure report's
# environment information (via allure-results/environment.properties).
TIMINGS: dict[str, float] = {}


@contextmanager
def _timed(label: str):
    """Measure how long a part of the run takes (wall-clock), for the report."""
    start = time.monotonic()
    try:
        yield
    finally:
        TIMINGS[label] = TIMINGS.get(label, 0.0) + time.monotonic() - start   # adds up repeated parts


def _write_environment() -> None:
    """Run facts for the Allure report: wall-clock times, plus where the tests ran."""
    # .properties keys can't contain spaces (a space ends the key), hence the underscores.
    lines = [f"Run = {RUN_DIR.name}", f"Python = {sys.version.split()[0]}", f"Platform = {sys.platform}",
             f"Parallel_workers = {_settings()['MSG_TEST_WORKERS']} (CPU cores: {os.cpu_count()})",
             f"Retry_failed_tests = {_settings()['MSG_TEST_RETRY']} (count: {_settings()['MSG_TEST_RETRY_COUNT']})"]
    lines += [f"Duration_{label} = {seconds:.1f} s" for label, seconds in TIMINGS.items()]
    if TIMINGS:
        lines.append(f"Duration_total = {sum(TIMINGS.values()):.1f} s")
    ALLURE_RESULTS.mkdir(parents=True, exist_ok=True)
    (ALLURE_RESULTS / "environment.properties").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _settings() -> dict[str, str]:
    """Test settings: tests/test.env, overridden by variables set in the environment."""
    values = {}
    for line in (ROOT / "tests" / "test.env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return {**values, **{k: v for k, v in os.environ.items() if k in values}}


def _pytest(session: nox.Session, name: str, marker: str, *extra: str) -> None:
    """Run pytest for one marker: its own log, results into the shared Allure folder."""
    session.run(
        "pytest", "-m", marker, *extra,
        f"--log-file={RUN_DIR / (name + '.log')}",     # these override the defaults in pytest.ini
        f"--output={RUN_DIR / 'playwright'}",         # traces/screenshots of failed UI tests
        f"--alluredir={ALLURE_RESULTS}",              # shared by all runs -> one Allure report
        "--allure-no-capture",                        # logs are attached with test names instead (tests/conftest.py)
        *session.posargs,
        success_codes=OK_CODES,
    )


def _allure_report(session: nox.Session) -> None:
    """Build one Allure report from every pytest run so far in this nox run."""
    if not shutil.which("allure"):
        session.warn("Allure CLI not found (npm install -g allure): skipping the combined report")
        return
    _write_environment()
    shutil.rmtree(ALLURE_REPORT, ignore_errors=True)   # rebuilt with this run's results so far
    # `awesome` is Allure 3's standard report; --single-file puts it all in one index.html
    session.run("allure", "awesome", "--single-file", "--output", str(ALLURE_REPORT), str(ALLURE_RESULTS),
                external=True)
    session.log(f"Allure report: {ALLURE_REPORT / 'index.html'}  (one self-contained file: open it directly)")


@contextmanager
def _reported(session: nox.Session):
    """Rebuild the Allure report when the session ends, also when its tests failed."""
    try:
        yield
    finally:
        _allure_report(session)


def _install_browser(session: nox.Session) -> None:
    """Chromium for Playwright; quick if it's already downloaded."""
    command = ["playwright", "install", "chromium"]
    if sys.platform.startswith("linux") and os.environ.get("CI"):
        command.append("--with-deps")              # system libraries on a fresh CI machine
    session.run(*command)


def _is_listening(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    try:
        with socket.create_connection((parts.hostname, parts.port or 443), timeout=2):
            return True
    except OSError:
        return False


def _wait_until_healthy(session: nox.Session, url: str, ca_file: Path, timeout: float) -> None:
    context = ssl.create_default_context(cafile=str(ca_file))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/healthz", context=context, timeout=3) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(1)
    session.error(f"Server did not become healthy within {timeout:.0f}s. Check: docker compose logs")


@contextmanager
def _server(session: nox.Session):
    """One server for the whole session: started here unless one is already running."""
    settings = _settings()
    url = settings["MSG_URL"].rstrip("/")
    if _is_listening(url):
        session.log(f"Using the server already running at {url} (left running afterwards)")
        yield
        return

    ca_file = ROOT / settings["MSG_CA_FILE"]
    if not ca_file.is_file():
        session.log("No certificate yet: creating one")
        session.run("python", "scripts/gen_certs.py")

    compose_env = {"USERS_FILE": settings["USERS_FILE"]}    # demo users, as in tests/test.env
    with _timed("server_start"):
        session.run("docker", "compose", "up", "--build", "-d", env=compose_env, external=True)
    try:
        with _timed("server_start"):
            _wait_until_healthy(session, url, ca_file, float(settings["MSG_SERVER_START_TIMEOUT"]))
        yield
    finally:
        session.run("docker", "compose", "down", external=True)


@nox.session(reuse_venv=True)
def unit(session):
    """Unit tests: redaction and audit log. No server needed."""
    session.install("-r", "requirements-dev.txt")
    with _reported(session):
        with _timed("unit_tests"):
            _pytest(session, "unit", "unit")


@nox.session(reuse_venv=True)
def integration(session):
    """API, CLI and UI tests against one shared server.

    Most run in parallel (MSG_TEST_WORKERS workers, default: one per CPU core); tests marked `serial`
    (restarting the server, or relying on nobody else writing) run afterwards, alone,
    also when a parallel test failed, so their results are never hidden.
    """
    session.install("-r", "requirements-dev.txt")
    _install_browser(session)
    with _reported(session), _server(session):
        workers = _settings()["MSG_TEST_WORKERS"]          # tests/test.env, or your environment
        parallel_failed = False
        try:
            with _timed("integration_tests_parallel"):
                _pytest(session, "integration", "(api or ui) and not serial", "-n", workers)
        except nox.command.CommandFailed:
            parallel_failed = True      # keep going: the serial tests still run and get reported
        with _timed("integration_tests_serial"):
            _pytest(session, "integration-serial", "(api or ui) and serial")
        if parallel_failed:
            session.error("Some parallel tests failed (see above)")   # the session still fails


@nox.session(reuse_venv=True)
def api(session):
    """API and CLI tests only."""
    session.install("-r", "requirements-dev.txt")
    with _reported(session):
        with _timed("api_cli_tests"):
            _pytest(session, "api", "api")


@nox.session(reuse_venv=True)
def ui(session):
    """Playwright tests only."""
    session.install("-r", "requirements-dev.txt")
    _install_browser(session)
    with _reported(session):
        with _timed("ui_tests"):
            _pytest(session, "ui", "ui")
