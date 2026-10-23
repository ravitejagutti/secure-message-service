"""MessageClient: thin httpx-based wrapper around the Secure Message Service API.

Usable standalone (``import msgclient; msgclient.MessageClient(...)``) or via
the ``msgclient`` CLI in cli.py.
"""

from __future__ import annotations

import ssl
from pathlib import Path

import httpx


_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CA_FILE = str(_PROJECT_ROOT / "certs" / "server.crt")


class MessageClientError(Exception):
    """Base for errors raised by MessageClient."""


class AuthError(MessageClientError):
    """Raised on 401 (missing/invalid/expired token)."""


class ApiError(MessageClientError):
    """Raised on any other non-2xx response (404, 422, 5xx, ...)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(f"{status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class MessageClient:
    """Library client for the Secure Message Service.

    TLS is pinned to ``ca_file`` (the server's self-signed cert) rather than
    verified against the system trust store or disabled outright.
    """

    def __init__(
        self,
        base_url: str,
        token: str,
        ca_file: str | None = DEFAULT_CA_FILE,
        timeout: float = 10.0,
    ):
        if ca_file and not Path(ca_file).is_file():
            raise MessageClientError(f"CA file not found: {ca_file}")
        self._http = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {token}"},
            # Trust only our self-signed cert when given, else the system's CAs.
            verify=ssl.create_default_context(cafile=ca_file) if ca_file else True,
            timeout=timeout,
        )

    def send(self, content: str) -> dict:
        return self._request("POST", "/api/messages", json={"content": content})

    def list(self, limit: int = 50, offset: int = 0) -> list[dict]:
        return self._request(
            "GET", "/api/messages", params={"limit": limit, "offset": offset}
        )

    def get(self, message_id: int) -> dict:
        return self._request("GET", f"/api/messages/{message_id}")

    def delete(self, message_id: int) -> None:
        self._request("DELETE", f"/api/messages/{message_id}")

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "MessageClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> object:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.ConnectError as exc:
            raise MessageClientError(f"Could not connect to {self._http.base_url}: {exc}") from exc

        if response.status_code == 401:
            raise AuthError(_error_detail(response))
        if response.status_code >= 400:
            raise ApiError(response.status_code, _error_detail(response))

        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def _error_detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text
    return body.get("detail", response.text) if isinstance(body, dict) else response.text
