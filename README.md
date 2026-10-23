# Secure Message Service

A small HTTPS message service in Python. Messages are posted through a REST API, and any JWTs, email addresses, IPv4 addresses and credit card numbers are redacted **before** they are stored or displayed. Includes a server-rendered web page, a Python client (CLI + library), and pytest/Playwright tests.

| Requirement |                                                 Where                                 |
| ----------- | ------------------------------------------------------------------------------------- |
| Accept, return, delete messages via API | `POST/GET /api/messages`, `GET/DELETE /api/messages/{id}` |
| Basic web page (table) | `GET /` |
| Redaction before storage and display | `server/app/redaction.py`, applied in `server/app/service.py` |
| Docker | `Dockerfile`, `docker-compose.yml` |
| Python client, CLI + automation | `client/msgclient` (`msgclient` command, `MessageClient` class) |
| Automated tests | `tests/unit`, `tests/api`, `tests/ui` |
| Persistence | SQLite file on the `./data` volume |
| Authentication (preloaded, no registration) | `config/users.json`, loaded at startup |
| TLS, self-signed | `scripts/gen_certs.py`; the server only listens on HTTPS |

## Run the app

Prerequisites: Docker (with Compose) and Python 3.10+. The commands below work the same on Windows (PowerShell), macOS and Linux; on macOS/Linux use `python3` if `python` isn't available.

**Recommended: a virtual environment** for the Python packages used by the client, the tests and the helper scripts (the server itself runs in Docker). It keeps them separate from other Python projects on your machine. Create it once, and activate it in each new terminal:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
source .venv/bin/activate          # macOS / Linux
```

`.venv` is excluded from git: everyone creates their own from `requirements-dev.txt`. If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), allow local scripts for your user once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

```bash
# 1. Self-signed certificate (writes certs/server.crt and certs/server.key)
pip install cryptography
python scripts/gen_certs.py

# 2. Users file with the demo user (see config/README.md for the credentials)
cp config/users.example.json config/users.json      # PowerShell's cp works too

# 3. Build and start
docker compose up --build
```

The server runs at **https://localhost:8443**. Demo credentials for `alice`, local use only:

| For | Value |
| --- | --- |
| Web page (HTTP Basic) | username `alice`, password `changeme` |
| API and CLI (Bearer token) | `pRo1nGR3iigAbgNQbhmWgTHpc-4Yn_TF191Y_u53nZI` |

To create your own credentials instead: `python scripts/make_user.py alice` (prints a new password and token, stores only their hashes), then `docker compose restart`.

- **Web page:** open https://localhost:8443/ and log in. The browser shows "Not secure" because the certificate is self-signed; the connection is still encrypted.
- **API docs:** https://localhost:8443/docs. Click **Authorize** and paste the token under **HTTPBearer**.

**Stop the server:** press `Ctrl+C` in the terminal running `docker compose up` (or, if it runs in the background with `-d`, use `docker compose down`). Messages in `./data` and the audit log in `./logs` are kept for the next start.

### Use the client

```bash
pip install -e ./client

export MSG_URL=https://localhost:8443          # PowerShell: $env:MSG_URL = "https://localhost:8443"
export MSG_TOKEN=<api token>                   # PowerShell: $env:MSG_TOKEN = "<api token>"

msgclient send "mail me at ravi@example.com"   # -> content: "mail me at [REDACTED_EMAIL]"
msgclient list --limit 10                      # newest 10 messages
msgclient list --limit 10 --offset 10          # the next 10 (page 2)
msgclient get 1
msgclient delete 1
msgclient list --json                          # machine-readable output for scripts
```

The client trusts only `certs/server.crt` (found from the project root; override with `MSG_CA_FILE`). Exit codes: `0` success, `1` API error (e.g. 404), `2` usage/config error, `3` authentication error. Errors go to stderr, so stdout stays parseable.

As a library:

```python
from msgclient import MessageClient

with MessageClient("https://localhost:8443", token="<api token>") as client:
    message = client.send("card 4111 1111 1111 1111")
    print(message["content"])          # card [REDACTED_CREDIT_CARD]
```

## Run the tests

One command runs everything: unit tests first, then it builds and starts the server, runs the API, CLI and Playwright tests, and brings the server down again.

```bash
# Server already running (e.g. from "Run the app"): test it as it is
python scripts/run_tests.py --install --no-build   # first time
python scripts/run_tests.py --no-build             # all suites
python scripts/run_tests.py api --no-build         # one suite (suite name goes first)

# No server running: the runner starts its own, tests, and stops it
python scripts/run_tests.py --install              # first time / CI: installs test dependencies and Chromium
python scripts/run_tests.py                        # all suites: unit first, then API, CLI and UI
python scripts/run_tests.py unit                   # unit tests only (no server needed)
python scripts/run_tests.py api                    # API + CLI tests
python scripts/run_tests.py ui                     # Playwright tests
python scripts/run_tests.py ui --headed --slowmo 1000   # watch the browser tests
```

Without `--no-build`, the runner starts and stops its own server, and it refuses to run if one is already up: stop it first with `docker compose down`, or use the `--no-build` commands.

If the unit tests fail, the run stops there without starting the server. Each run writes a timestamped HTML report and log to `reports/`; failing UI tests also save a Playwright trace and screenshot.

**Pre-commit hook:** the unit tests also run before every `git commit` and block it if one fails. Enable it once per clone, with the venv active: `pre-commit install` (installed by `requirements-dev.txt` / `--install`).

**CI:** GitHub Actions (`.github/workflows/tests.yml`) runs on every pull request (drafts skipped) and on pushes to `main`: the unit tests first, then, only if they pass, the same `python scripts/run_tests.py --install` on a fresh Linux machine. The HTML reports and logs are attached to each run.

| Suite | What it checks |
| --- | --- |
| Unit | Redaction of each data type, false positives (invalid IPs, Luhn-failing numbers, phone numbers, dates), audit log format |
| API | Create/list/get/delete, validation, auth on every route, TLS, redaction **in the database file itself**, persistence across a restart, audit log entries |
| CLI | `msgclient` as a subprocess: `--json` output, exit codes, error messages |
| UI (Playwright) | The page shows placeholders and never raw values, HTML is escaped, deleted messages disappear, no access without login |

More detail (credentials, server lifecycle, reports, tracing, running pytest directly): [docs/TESTING.md](docs/TESTING.md).

## Design notes

An architecture diagram, the main decisions (redaction on write, regex + validator detection, two auth mechanisms, hard delete, audit log, shared message board) and the reasons for them are in [docs/DESIGN.md](docs/DESIGN.md).

## Difficulties encountered

- **A credit card bug the first tests missed.** The first card pattern matched as many digits as possible, so `4111 1111 1111 1111 123` (card + CVV) was matched as one 19-digit number, failed the Luhn check, and was stored **in clear text**. The fix splits each run of digit groups and redacts the longest Luhn-valid span inside it. The regression cases are in `test_card_next_to_other_digits_is_redacted`.
- **Choosing how strict the email pattern should be.** A strict pattern left part of addresses like `ravi!k@example.com` visible. Redaction should fail safe, so the part before `@` is now permissive.
- **Thread safety with SQLite.** FastAPI runs requests on worker threads, while Python's SQLite connection refuses cross-thread use by default. Disabling that check required adding a re-entrant lock so threads take turns on the shared connection.
- **Self-signed TLS in every tool.** httpx can pin a CA file, but browsers can't; the Playwright context ignores certificate errors, and TLS verification is tested separately with the pinned cert.
- **Bearer auth missing from `/docs`.** The token was originally read from the header by hand, so FastAPI didn't know about it and Swagger UI had no token field. Declaring it with `HTTPBearer` fixed this.

## Room for improvement

- **Repository returns raw SQLite rows.** Next step: return `Message` objects behind a `MessageRepository` interface, so the database can be swapped without touching the service layer.
- **Scaling.** The service is single-instance by design: SQLite allows one writer and its file can't be shared between containers. To scale horizontally: move to Postgres with a connection pool (only `repository.py` changes), run several stateless app containers behind a load balancer, and terminate TLS at the load balancer.
- **Token lifecycle.** Tokens don't expire, can't be revoked without editing `users.json` and restarting, and have no scopes (e.g. read-only).
- **Password hashing.** bcrypt is fine; Argon2id is OWASP's first choice for new systems.
- **Redaction coverage.** Not detected: IPv6, phone numbers, names, unsigned JWTs (`alg: none`, empty signature), and secrets other than JWTs (API keys, passwords). A pluggable detector list or an NER-based scanner would extend this.
- **Web page login.** HTTP Basic has no logout, expiry or error message: the browser resends the password until it's closed, and a wrong password just shows the prompt again. A login form with a short-lived, HttpOnly session cookie would add all three, and make successful logins meaningful to audit.
- **Authorization.** Restrict delete to the message's author (return 403 otherwise), and optionally let each user see only their own messages.
- **Update endpoint.** Not required; if added, updates must also go through `redact()`.
- **Container hardening.** Run as a non-root user, add a health check to `docker-compose.yml`, and close the database connection on shutdown.
- **Merge gate.** Make the `unit` and `integration` checks required before merging into `main` (a branch ruleset), so a red pipeline blocks the merge.
- **Skip CI for doc-only changes.** The pipeline also runs when only Markdown files change (~2 minutes). A plain `paths-ignore` would skip it, but with required checks a doc-only PR would then wait forever for checks that never run; the safe way is a small job that detects changed files and lets the test jobs report as skipped.
- **Test runner built on standard tools.** `scripts/run_tests.py` is hand-written to get fast feedback and a guaranteed server teardown in one command. In a team project I'd use nox sessions (`unit`, `api`, `ui`) in place of the script, a pytest session fixture with testcontainers to start and stop the server, with the unit/integration split kept as CI stages (as in the pipeline). That also gives one report per run instead of two.
