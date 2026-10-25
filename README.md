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

Prerequisite: **Docker** (with Compose). That's all for running the server:

```bash
docker compose up --build
```

On the first start, a small `init` container creates what's missing and exits: the self-signed certificate (`certs/`) and `config/users.json`, copied from the demo users (with a warning: public credentials, local use only). It never overwrites existing files, so later starts skip it. Then the app starts.

The client, the tests, the pre-commit hook and `scripts/make_user.py` run on your machine and need **Python 3.10+**, ideally in a virtual environment. Create it once, and activate it in each new terminal:

```bash
python -m venv .venv
.venv\Scripts\Activate.ps1        # Windows PowerShell
source .venv/bin/activate          # macOS / Linux
pip install -r requirements-dev.txt
```

`.venv` is excluded from git. On macOS/Linux use `python3` if `python` isn't available. If PowerShell refuses to run `Activate.ps1` ("running scripts is disabled"), allow local scripts for your user once with `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

The server runs at **https://localhost:8443**. Demo credentials for `alice`, local use only:

| For | Value |
| --- | --- |
| Web page (HTTP Basic) | username `alice`, password `changeme` |
| API and CLI (Bearer token) | `pRo1nGR3iigAbgNQbhmWgTHpc-4Yn_TF191Y_u53nZI` |

To create your own credentials instead: `python scripts/make_user.py alice` (prints a new password and token, stores only their hashes; use it to add a user or give one a new password and token). To remove a user, delete their entry from `config/users.json`. The running server picks up changes to that file on the next request, so no restart is needed. Don't copy an existing entry to add a user: the file holds hashes, so the copy would share the original user's password and token.

- **Web page:** open https://localhost:8443/ and log in. The browser shows "Not secure" because the certificate is self-signed; the connection is still encrypted.
- **API docs:** https://localhost:8443/docs. Click **Authorize** and paste the token under **HTTPBearer**.

**Stop the server:** press `Ctrl+C` in the terminal running `docker compose up` (or, if it runs in the background with `-d`, use `docker compose down`). Messages in `./data` and the audit log in `./logs` are kept for the next start.

**Debugging the server code:** to use breakpoints, run the server locally instead of in Docker (stop the container first): `pip install -r server/requirements.txt`, then `python -m server.app.main`. It uses the same `certs/`, `config/`, `data/` and `logs/` folders, so the client and the tests work against it unchanged.

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

The tests run with [nox](https://nox.thea.codes): each session gets its own clean virtual environment.

```bash
pip install -r requirements-dev.txt      # once, in your venv: installs nox and the test tools
npm install -g allure                    # once, optional: the Allure CLI (needs Node.js) for the combined report

nox                                      # unit tests, then API + CLI + UI; stops if a unit test fails
nox -s unit                              # unit tests only (no server needed)
nox -s integration                       # API + CLI + UI: in parallel, then the serial tests
nox -s api                               # API + CLI tests only (one after another)
nox -s ui                                # Playwright tests only (one after another)
nox -s ui -- --headed --slowmo 1000      # anything after -- goes to pytest: here, watch the browser
```

**Server:** for `nox` / `nox -s integration`, nox starts the server once before the tests and stops it afterwards (creating the self-signed certificate first if it's missing). For `nox -s api`, `nox -s ui` and plain `pytest`, a test fixture does the same. Either way, a server that's already running is used and left running.

**Parallel tests:** most API, CLI and UI tests run in parallel ([pytest-xdist](https://pytest-xdist.readthedocs.io), `MSG_TEST_WORKERS` workers, default one per CPU core). The 3 tests marked `serial` run afterwards, alone: they restart the server, read the SQLite file directly, or rely on nobody else writing. They run even when a parallel test failed, so their results are always reported.

**Retries:** failed API, CLI and UI tests can be retried (`MSG_TEST_RETRY=true`, up to `MSG_TEST_RETRY_COUNT` extra attempts; [pytest-rerunfailures](https://github.com/pytest-dev/pytest-rerunfailures)). Off by default, and never for unit tests: a test that only passes on a retry is flaky and should be fixed, not hidden. Retried attempts show in the Allure report.

**Report:** each run gets its own folder, `reports/<date_time>/`, so earlier runs are kept. It holds **one Allure report** for all tests of the run, `allure-report/index.html`, a single file that opens directly in a browser. It shows tests grouped by layer (Unit, API, CLI, UI), each test's logs, a screenshot and the page URL for failed UI tests, and the wall-clock time of each part of the run. Next to it: a text log per pytest run, and Playwright traces of failed UI tests. Without the Allure CLI, the report is skipped with a note; the tests still run.

**Settings:** defaults are in `tests/test.env` (server URL, certificate, the demo user from `config/users.example.json`, timeouts, `MSG_TEST_WORKERS`, `MSG_TEST_RETRY`); a variable set in your environment wins. When the tests start the server, it uses the demo users file. When testing a server you started yourself, the credentials the tests use (`MSG_USER`, `MSG_PASSWORD`, `MSG_TOKEN`, or the demo user) must exist in your `config/users.json`.

**Pre-commit hook:** the unit tests also run before every `git commit` and block it if one fails. Enable it once per clone, with the venv active: `pre-commit install`.

**CI:** GitHub Actions (`.github/workflows/tests.yml`) runs `nox` in one job on every pull request (drafts skipped) and on pushes to `main`, on a fresh Linux machine. The `tests` check is required before merging. The Allure report and logs are attached to each run (artifact `test-reports`). Two more workflows use Claude: `claude-code-review.yml` reviews each pull request and posts inline comments (drafts skipped), and `claude.yml` answers when someone writes `@claude` in an issue or PR comment. Both are read-only and need the `CLAUDE_CODE_OAUTH_TOKEN` repo secret.

| Suite | What it checks |
| --- | --- |
| Unit | Redaction of each data type, false positives (invalid IPs, Luhn-failing numbers, phone numbers, dates), audit log format |
| API | Create/list/get/delete, validation, auth on every route, TLS, redaction **in the database file itself**, persistence across a restart, audit log entries |
| CLI | `msgclient` as a subprocess: `--json` output, exit codes, error messages |
| UI (Playwright) | The page shows placeholders and never raw values, HTML is escaped, deleted messages disappear, no access without login |

More detail (sessions, server lifecycle, parallel and serial tests, settings, reports, debugging UI tests, plain pytest): [docs/TESTING.md](docs/TESTING.md).

## Design notes

An architecture diagram, the main decisions (redaction on write, regex + validator detection, two auth mechanisms, hard delete, audit log, shared message board) and the reasons for them are in [docs/DESIGN.md](docs/DESIGN.md).

## Difficulties encountered

- **A credit card bug the first tests missed.** The first card pattern matched as many digits as possible, so `4111 1111 1111 1111 123` (card + CVV) was matched as one 19-digit number, failed the Luhn check, and was stored **in clear text**. The fix splits each run of digit groups and checks every span inside it. A self-review after submission found a second case: a number right before a card can form its own valid span ending inside the card (`123456789 4831 …`), which left the rest of the card visible. Now every valid span from every start position is redacted, and overlapping spans become one placeholder. The regression cases are in `test_card_next_to_other_digits_is_redacted` and `test_card_overlapping_a_valid_span_before_it_is_fully_redacted`.
- **Choosing how strict the email pattern should be.** A strict pattern left part of addresses like `ravi!k@example.com` visible. Redaction should fail safe, so the part before `@` is now permissive.
- **Thread safety with SQLite.** FastAPI runs requests on worker threads, while Python's SQLite connection refuses cross-thread use by default. Disabling that check required adding a re-entrant lock so threads take turns on the shared connection.
- **Self-signed TLS in every tool.** httpx can pin a CA file, but browsers can't; the Playwright context ignores certificate errors, and TLS verification is tested separately with the pinned cert.
- **Bearer auth missing from `/docs`.** The token was originally read from the header by hand, so FastAPI didn't know about it and Swagger UI had no token field. Declaring it with `HTTPBearer` fixed this.
- **Running the tests in parallel exposed a race.** The test that reads the SQLite file directly (to prove raw values never reach storage) failed with "attempt to write a readonly database", and a concurrent delete returned 500: it opened the file from the host while the server, inside the container, was writing to it, and file locks don't coordinate across that boundary. Such tests are now marked `serial` and run alone after the parallel ones.

## Room for improvement

- **Repository returns raw SQLite rows.** Next step: return `Message` objects behind a `MessageRepository` interface, so the database can be swapped without touching the service layer.
- **Scaling.** The service is single-instance by design: SQLite allows one writer and its file can't be shared between containers. To scale horizontally: move to Postgres with a connection pool (only `repository.py` changes), run several stateless app containers behind a load balancer, and terminate TLS at the load balancer.
- **Token lifecycle.** Tokens don't expire and have no scopes (e.g. read-only). Revoking one means editing `users.json` (it takes effect immediately, but it's a manual file edit).
- **Password hashing.** bcrypt is fine; Argon2id is OWASP's first choice for new systems.
- **Redaction coverage.** Not detected: IPv6, phone numbers, names, unsigned JWTs (`alg: none`, empty signature), and secrets other than JWTs (API keys, passwords). A pluggable detector list or an NER-based scanner would extend this.
- **Web page login.** HTTP Basic has no logout, expiry or error message: the browser resends the password until it's closed, and a wrong password just shows the prompt again. A login form with a short-lived, HttpOnly session cookie would add all three, and make successful logins meaningful to audit.
- **Authorization.** Restrict delete to the message's author (return 403 otherwise), and optionally let each user see only their own messages.
- **Update endpoint.** Not required; if added, updates must also go through `redact()`.
- **Container hardening.** Run as a non-root user, add a health check to `docker-compose.yml`, and close the database connection on shutdown.
- **Skip CI for doc-only changes.** The pipeline also runs when only Markdown files change (~2 minutes). A plain `paths-ignore` would skip it, but with required checks a doc-only PR would then wait forever for checks that never run; the safe way is a small job that detects changed files and lets the test jobs report as skipped.
- **User management.** Users live in a JSON file (reloaded automatically when it changes), so adding a user means running a script on the server's machine, and test runs rely on the demo user. Next step: store users in the database, created through an admin endpoint, so tests and CI can create their own throwaway users.
- **Parallel runs on one machine.** Tests within a run are parallel, but two runs at once would clash on the fixed port 8443; that would need random ports, a unique compose project and separate data folders per run.
- **Report history and sharing.** Keep Allure's history between runs to show trends (e.g. a test that failed 3 of the last 10 runs), and publish the CI report to GitHub Pages so it opens with a link instead of a download.
