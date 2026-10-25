# Testing

Details behind the "Run the tests" section of the [README](../README.md).

## Setup

```bash
pip install -r requirements-dev.txt      # in your venv: nox, pytest and plugins, Playwright, Allure adapter
npm install -g allure                    # optional: Allure 3 CLI (needs Node.js), builds the combined report
pre-commit install                       # optional: unit tests before every commit
```

Docker Desktop must be running for the API, CLI and UI tests.

## Sessions (nox)

The tests run with [nox](https://nox.thea.codes), configured in `noxfile.py`. Each session gets its own clean virtual environment (in `.nox/`) and installs `requirements-dev.txt`.

| Command | Runs | Server |
| --- | --- | --- |
| `nox` | `unit`, then `integration`; stops at the first failing session | Only for `integration` |
| `nox -s unit` | `pytest -m unit`: redaction and audit log | None |
| `nox -s integration` | API, CLI and UI tests: everything not marked `serial` in parallel, then the `serial` tests alone | Started once by nox |
| `nox -s api` | `pytest -m api`: API and CLI tests, one after another | Started by the test fixture |
| `nox -s ui` | `pytest -m ui`: Playwright tests, one after another | Started by the test fixture |

Anything after `--` goes to pytest, e.g. `nox -s api -- -k delete`.

**Fast feedback:** plain `nox` runs the unit tests first (no server). If one fails, nox stops there, without building the server or running the slower suites.

## Server lifecycle

| Who starts it | When |
| --- | --- |
| **nox** (`_server()` in `noxfile.py`) | `nox` and `nox -s integration`: once before pytest; always stopped afterwards (`docker compose down`), even if tests fail. All parallel workers share this one server. |
| **The `server_url` fixture** (`tests/conftest.py`, with Testcontainers) | `nox -s api`, `nox -s ui` and plain `pytest`: when the first API/CLI/UI test needs it; stopped after the last test. Unit-only runs never start Docker. |

Both behave the same way:

| Situation | What happens |
| --- | --- |
| Nothing on `MSG_URL` | Create the certificate if it's missing (`scripts/gen_certs.py`), `docker compose up --build`, wait for `/healthz` (up to `MSG_SERVER_START_TIMEOUT` seconds), test, stop. `./data` and `./logs` are kept. |
| This project's server already running (e.g. your `docker compose up`) | Use it and leave it running. Rebuild it first (`docker compose up --build -d`) after code changes. |
| Something else on that port (e.g. a server from another clone, with a different certificate) | Stop at once with a message saying what was found and what to do |

## Parallel and serial tests

`nox -s integration` runs the API, CLI and UI tests with [pytest-xdist](https://pytest-xdist.readthedocs.io): `MSG_TEST_WORKERS` worker processes, each running its share of tests one after another (`auto` = one per CPU core). Each test creates and deletes its own data, so tests don't depend on each other or on their order.

A few tests can't run alongside others. They're marked `@pytest.mark.serial`, with the reason next to the marker, and run afterwards, alone, against the same server (also when a parallel test failed, so their results are never hidden):

| Test | Why it's serial |
| --- | --- |
| `test_message_survives_container_restart` | Restarts the server under everything else |
| `test_raw_values_never_reach_the_database` | Reads the SQLite file directly from the host while the server (in the container) may be writing to it; file locks don't coordinate across that boundary |
| `test_list_supports_limit_and_offset` | Its two pages shift if another test creates a message in between |

**Rule for new tests:** a test that restarts the server, reads a server-owned file directly (like the database), or depends on what *other* tests write, must be marked `serial`. `--strict-markers` (in `pytest.ini`) makes a misspelled marker an error instead of a silently ignored one.

## Retries

Failed API, CLI and UI tests can be retried automatically:

```powershell
$env:MSG_TEST_RETRY = "true"          # or set it in tests/test.env
$env:MSG_TEST_RETRY_COUNT = "2"       # extra attempts per failed test (default 2), 1 s apart
nox
```

- **Off by default.** A test that only passes on a retry is flaky: a race, a timing assumption, or a real intermittent bug. It should be fixed, not hidden; retries are a safety net for an unreliable environment, not a fix.
- **Never for unit tests.** They're deterministic, so a retry could only hide a real bug.
- **Visible:** the console shows `R` for each rerun and a `rerun` count in the summary; the Allure report lists each test's attempts, and its environment section shows whether retries were on (`Retry_failed_tests`).
- Implemented in `tests/conftest.py` with [pytest-rerunfailures](https://github.com/pytest-dev/pytest-rerunfailures)' `flaky` marker, so it works the same for nox, plain pytest and CI, and with parallel workers.

## Settings

Test settings are environment variables. Their defaults are in `tests/test.env`; any variable already set in your environment wins over that file.

| Variable | Default | Used for |
| --- | --- | --- |
| `MSG_URL` | `https://localhost:8443` | Server under test |
| `MSG_CA_FILE` | `certs/server.crt` | Certificate the tests trust |
| `MSG_SERVER_START_TIMEOUT` | `60` | Seconds to wait for the server after a (re)start; raise it on slow machines |
| `MSG_TEST_WORKERS` | `auto` | Parallel workers for `nox -s integration`: a number, or `auto` (one per CPU core) |
| `MSG_TEST_RETRY`, `MSG_TEST_RETRY_COUNT` | `false`, `2` | Retry failed API, CLI and UI tests (never unit tests). Off by default: a test that only passes on a retry is flaky and should be fixed; retried attempts show in the Allure report. |
| `MSG_USER`, `MSG_PASSWORD`, `MSG_TOKEN` | The demo user (`alice`) | Credentials the tests log in with |
| `USERS_FILE` | `config/users.example.json` | Users file for a server the tests start themselves |
| `MSG_DB_PATH`, `MSG_AUDIT_LOG` | `data/messages.db`, `logs/audit.log` | Host files some tests inspect directly |

**Credentials rule:** the credentials the tests use must exist in the users file the server loaded:

- **The tests start the server:** it loads `USERS_FILE` (the demo users file), and the tests use the demo user. This always matches.
- **You started the server:** it loads your `config/users.json`. If that file was copied from the example, the demo user works as is. If you created your own user with `make_user.py`, set the three `MSG_*` variables to it (PowerShell):

```powershell
$env:MSG_USER = "<name>"; $env:MSG_PASSWORD = "<password>"; $env:MSG_TOKEN = "<token>"
```

If the server rejects the credentials, the run stops at the first request with a message saying so (check for leftover `MSG_*` variables in your shell).

## Reports

Each `nox` run gets its own folder, named by its start time, so earlier runs are kept:

```
reports/2026-10-24_16-40-00/
├── allure-report/index.html     one report for every test of the run (a single file)
├── allure-results/              the raw results it's built from
├── unit.log, integration.log, integration-serial.log
└── playwright/                  traces and screenshots of failed UI tests
```

The **Allure report** is rebuilt after each session, also when tests fail, so it always covers the run so far. It shows:

- every test, grouped by layer: **Unit, API, CLI, UI**
- each test's captured logs and output, attached per phase and named after the test (e.g. `test_create_message_returns_201_with_details - log (call)`)
- for a failed UI test: a screenshot of the page at the moment of failure and its URL, named after the test
- for a retried test: each attempt
- in the environment section: the wall-clock time of each part of the run (`Duration_unit_tests`, `Duration_server_start`, `Duration_integration_tests_parallel`, `Duration_integration_tests_serial`, `Duration_total`), the number of parallel workers, whether retries were on, Python version and platform

The header's duration is Allure's own figure: from the first test's start to the last test's end, including the setup in between.

Without the Allure CLI, nox skips the report with a note; the tests and logs are unaffected. In CI, the whole run folder is attached to the run as the `test-reports` artifact.

**Text logs:** one per pytest run, with `START` / `RESULT` lines around each test and every HTTP request (`method URL -> status`) and CLI call (`command -> exit code`). Message bodies are never logged. In the parallel run, this file holds the main process's lines; each test's own lines are in the Allure report.

## Debugging UI tests

They run headless by default (CI machines have no screen). To watch them in a visible browser, slowed down:

```bash
nox -s ui -- --headed --slowmo 1000
```

When a UI test fails, its screenshot is in the Allure report, and a Playwright **trace** (every action, with DOM snapshots, network calls and console output) is saved in the run folder under `playwright/<test>/`. Open it in a step-by-step viewer with `playwright show-trace <path>/trace.zip`, or drop it on https://trace.playwright.dev.

## Without nox

The same tests run with plain pytest in your venv; the fixture starts and stops the server when needed, and tests run one after another:

```bash
pip install -r requirements-dev.txt
playwright install chromium

pytest -m unit          # unit tests; no server needed
pytest                  # everything
pytest -n 4 -m "not serial"   # parallel, as nox does, against a server you started yourself
```

## What each suite checks

| Suite | What it checks |
| --- | --- |
| `tests/unit/test_redaction.py` | Each data type, false positives (invalid IPs, Luhn-failing numbers, phone numbers, dates), edge cases |
| `tests/unit/test_audit.py` | Audit log line format, sanitizing of request values |
| `tests/api/test_api.py` | Create/list/get/delete, validation (422), 404s, redaction in responses and **in the database file itself**, auth on every route, TLS, persistence across a container restart, audit log entries in `logs/audit.log` (and no message content in them) |
| `tests/api/test_cli.py` | The CLI as a subprocess: `--json` output, exit codes, clean error messages |
| `tests/ui/test_ui.py` | Playwright: the page shows placeholders and never raw values, HTML in messages is escaped (no script runs), deleted messages disappear, no access without login |

The persistence test runs `docker compose restart` and is skipped if the `docker` CLI isn't available.
