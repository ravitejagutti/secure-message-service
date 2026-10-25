`users.example.json` is a sample credentials file, loaded via `USERS_FILE`. On the first `docker compose up`, the `init` container copies it to `users.json` if that file doesn't exist yet (it never overwrites it).

Demo credentials for `alice` (do not reuse anywhere real):
- Password (HTTP Basic, for the web page): `changeme`
- API token (`Authorization: Bearer <token>`): `pRo1nGR3iigAbgNQbhmWgTHpc-4Yn_TF191Y_u53nZI`

Only the bcrypt password hash and SHA-256 token hash are stored in the JSON file; the plaintext values above exist only here, for local testing.

To create your own user instead (prints a new password and token once, stores only their hashes in `users.json`):

```bash
python scripts/make_user.py alice
```

A running server picks up changes to `users.json` on the next request; no restart is needed.

- **Add a user, or give one a new password and token:** `make_user.py <name>`.
- **Remove a user** (revoke their access): delete their entry from `users.json`.
- **Don't copy an existing entry** to add a user: the file holds hashes, so the copy would share the original user's password and token.

When the tests start the server themselves, it uses `users.example.json` (set in `tests/test.env`). When you start it, it uses `users.json` (see the main README).
