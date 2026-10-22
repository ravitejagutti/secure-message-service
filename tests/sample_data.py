"""Sample sensitive values shared by the API, CLI and UI tests. Test data only."""

JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    ".eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IlRlc3QgVXNlciJ9"
    ".dummySignature123-abc"
)
EMAIL = "ravi@example.com"
IPV4 = "192.168.10.20"
CARD = "4111 1111 1111 1111"
RAW_VALUES = [JWT, EMAIL, IPV4, CARD]
PLACEHOLDERS = [
    "[REDACTED_JWT]",
    "[REDACTED_EMAIL]",
    "[REDACTED_IPV4]",
    "[REDACTED_CREDIT_CARD]",
]


def sensitive_message(tag: str) -> str:
    return f"{tag} token {JWT} mail {EMAIL} ip {IPV4} card {CARD}"
