`users.example.json` is a sample credentials file, loaded via `USERS_FILE`. Copy it to `users.json` to try the service locally.

Demo credentials for `alice` (do not reuse anywhere real):
- Password (HTTP Basic, for the web page): `changeme`
- API token (`Authorization: Bearer <token>`): `pRo1nGR3iigAbgNQbhmWgTHpc-4Yn_TF191Y_u53nZI`

Only the bcrypt password hash and SHA-256 token hash are stored in the JSON file; the plaintext values above exist only here, for local testing.

To create your own user instead (prints a new password and token once, stores only their hashes in `users.json`):

```bash
python scripts/make_user.py alice
docker compose restart
```

Test runs started with `scripts/run_tests.py` use `users.example.json` unless `MSG_USER`, `MSG_PASSWORD` and `MSG_TOKEN` are set (see the main README).
