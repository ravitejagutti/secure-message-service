import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    db_path: str
    users_file: str
    ssl_certfile: str
    ssl_keyfile: str
    port: int


def get_settings() -> Settings:
    return Settings(
        db_path=os.environ.get("DB_PATH", "data/messages.db"),
        users_file=os.environ.get("USERS_FILE", "config/users.json"),
        ssl_certfile=os.environ.get("SSL_CERTFILE", "certs/server.crt"),
        ssl_keyfile=os.environ.get("SSL_KEYFILE", "certs/server.key"),
        port=int(os.environ.get("PORT", "8443")),
    )
