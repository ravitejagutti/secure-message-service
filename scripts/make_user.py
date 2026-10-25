"""Create a demo user for the Secure Message Service.

Generates a random password and API token, writes their hashes to
config/users.json, and prints the plain values (shown only once).

Usage (from the project root):
    python scripts/make_user.py alice
"""

import hashlib
import json
import secrets
import sys
from pathlib import Path

import bcrypt

USERS_FILE = Path(__file__).resolve().parents[1] / "config" / "users.json"


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("Usage: python scripts/make_user.py <username>")
    username = sys.argv[1]

    password = secrets.token_urlsafe(12)   # 16 characters, well under bcrypt's 72-byte limit
    token = secrets.token_urlsafe(32)      # 43 characters of random data

    user = {
        "username": username,
        "password_bcrypt": bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode(),
        "api_token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }

    # Replace any existing entry with the same username, keep the others.
    users = json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else []
    users = [u for u in users if u["username"] != username] + [user]

    USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
    USERS_FILE.write_text(json.dumps(users, indent=2) + "\n")

    print(f"Updated {USERS_FILE}")
    print(f"username : {username}")
    print(f"password : {password}")
    print(f"api token: {token}")
    print("Save these now: only their hashes are stored. A running server picks them up on the next request.")


if __name__ == "__main__":
    main()