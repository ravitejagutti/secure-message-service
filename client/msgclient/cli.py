"""Command-line interface for msgclient.

Usage:
    msgclient send CONTENT [--json]
    msgclient list [--limit N] [--offset N] [--json]
    msgclient get ID [--json]
    msgclient delete ID [--json]

Reads MSG_URL and MSG_TOKEN (required), and MSG_CA_FILE (optional, defaults
to certs/server.crt) from the environment.

Exit codes: 0 success, 1 HTTP/API error (e.g. 404), 2 usage error,
3 auth error. Errors always go to stderr so stdout stays parseable
(e.g. with --json for automation).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from .client import DEFAULT_CA_FILE, AuthError, MessageClient, MessageClientError

EXIT_OK = 0
EXIT_API_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_AUTH_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msgclient")
    subparsers = parser.add_subparsers(dest="command", required=True)

    send = subparsers.add_parser("send", help="Create a message")
    send.add_argument("content")
    send.add_argument("--json", action="store_true")

    list_cmd = subparsers.add_parser("list", help="List messages")
    list_cmd.add_argument("--limit", type=int, default=50)
    list_cmd.add_argument("--offset", type=int, default=0)
    list_cmd.add_argument("--json", action="store_true")

    get = subparsers.add_parser("get", help="Get a message by id")
    get.add_argument("id", type=int)
    get.add_argument("--json", action="store_true")

    delete = subparsers.add_parser("delete", help="Delete a message by id")
    delete.add_argument("id", type=int)
    delete.add_argument("--json", action="store_true")

    return parser


def _client_from_env() -> MessageClient:
    base_url = os.environ.get("MSG_URL")
    token = os.environ.get("MSG_TOKEN")
    if not base_url or not token:
        print("MSG_URL and MSG_TOKEN must be set", file=sys.stderr)
        sys.exit(EXIT_USAGE_ERROR)
    ca_file = os.environ.get("MSG_CA_FILE", DEFAULT_CA_FILE)
    try:
        return MessageClient(base_url, token, ca_file=ca_file or None)
    except MessageClientError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(EXIT_USAGE_ERROR)


def _print(result: object, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result))
    elif result is None:
        print("OK")
    else:
        print(result)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    with _client_from_env() as client:
        try:
            if args.command == "send":
                result = client.send(args.content)
            elif args.command == "list":
                result = client.list(limit=args.limit, offset=args.offset)
            elif args.command == "get":
                result = client.get(args.id)
            else:
                result = client.delete(args.id)
        except AuthError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_AUTH_ERROR
        except MessageClientError as exc:
            print(str(exc), file=sys.stderr)
            return EXIT_API_ERROR

    _print(result, args.json)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
