# Testing

Details behind the "Run the tests" section of the [README](../README.md).

## The test runner

One command runs any suite, or all of them. For the API and UI suites it also builds and starts the server and waits until it's healthy, unless you pass `--no-build` to test a server that's already running:

```bash
python scripts/run_tests.py --install    # fresh machine / CI: installs test dependencies
                                         # and Chromium, creates the cert if missing
python scripts/run_tests.py              # all suites: unit tests first, then the rest
python scripts/run_tests.py unit         # unit tests only: redaction, audit log (no server needed)
python scripts/run_tests.py api          # API + CLI tests
python scripts/run_tests.py ui           # Playwright tests
python scripts/run_tests.py --no-build   # all suites against the server already running
python scripts/run_tests.py api --no-build   # same, one suite (suite name goes first)
python scripts/run_tests.py api -k delete    # extra arguments go to pytest
```

**Fast feedback:** a full run starts with the unit tests (about a second, no server). If any fail, it stops there, without building the server or running the slower API and UI tests.

**Server lifecycle:** if the script started the server, it always brings it down at the end (`docker compose down`), even when tests fail or the run is interrupted; `./data` is kept. If a server is already running, the script won't start its own; it stops with a message pointing to `--no-build`, which tests the running server and leaves it alone:

| Where | Command |
| --- | --- |
| CI / fresh machine | `python scripts/run_tests.py --install`: sets up, starts the server, tests, brings it down |
| Local, server already running | `python scripts/run_tests.py --no-build` (or `api --no-build`, `ui --no-build`): rebuild first with `docker compose up --build -d` after code changes |

## Credentials

Credentials come from environment variables:

| `MSG_USER`, `MSG_PASSWORD`, `MSG_TOKEN` | Server uses | Tests log in with |
| --- | --- | --- |
| All three set | `config/users.json` | Your values |
| None, or only some (e.g. a `MSG_TOKEN` left over from using `msgclient`) | `config/users.example.json` | The demo user |

A partial set is ignored with a one-line note, since mixing your values with demo ones would make some logins pass and others fail. With `--no-build`, the tests use these variables (or the demo defaults) against the running server, so they must match the users file it started with. Example with your own user (PowerShell):

```powershell
$env:MSG_USER = "alice"; $env:MSG_PASSWORD = "<password>"; $env:MSG_TOKEN = "<token>"
python scripts/run_tests.py
```

## Reports and logs

Each run writes a timestamped report and log, e.g. `reports/api_2026-10-22_21-30-05.html` and `.log`, so results from earlier runs are kept for comparison. A full run writes two: `all-unit_...` and `all-integration_...`.

- **HTML report:** each test with its status (passed/failed/skipped) and duration; expand a test to see its logs.
- **Log file:** the whole run as text, with `START` / `RESULT` lines around each test and every HTTP request (`method URL -> status`) and CLI call (`command -> exit code`) in between. Message bodies are never logged.

Plain `pytest` runs write the same two files as `reports/report.html` and `reports/test-run.log`.

## Watching and debugging the UI tests

They run headless by default (CI machines have no screen). To watch them in a visible browser, slowed down:

```bash
python scripts/run_tests.py ui --headed --slowmo 1000
```

When a UI test fails, a Playwright **trace** (every action, with DOM snapshots, network calls and console output) and a screenshot are saved to `reports/playwright/<test>/`. Open the trace in a step-by-step viewer with `playwright show-trace reports/playwright/<test>/trace.zip`, or drop it on https://trace.playwright.dev. To record traces for passing tests too, add `--tracing on`.

## Without the runner

```bash
pip install -r requirements-dev.txt
playwright install chromium

pytest -m unit          # redaction rules; no server needed
pytest                  # everything; needs `docker compose up` running
```

## What each suite checks

| Suite | What it checks |
| --- | --- |
| `tests/unit/test_redaction.py` | Each data type, false positives (invalid IPs, Luhn-failing numbers, phone numbers, dates), edge cases |
| `tests/unit/test_audit.py` | Audit log line format, sanitizing of request values |
| `tests/api/test_api.py` | Create/list/get/delete, validation (422), 404s, redaction in responses and **in the database file itself**, auth on every route, TLS, persistence across a container restart, audit log entries in `logs/audit.log` (and no message content in them) |
| `tests/api/test_cli.py` | The CLI as a subprocess: `--json` output, exit codes, clean error messages |
| `tests/ui/test_ui.py` | Playwright: the page shows placeholders and never raw values, HTML in messages is escaped (no script runs), deleted messages disappear, no access without login |

Each test creates its own data and deletes it afterwards, so tests are independent of order and of existing data. The persistence test runs `docker compose restart` and is skipped if the `docker` CLI isn't available.
