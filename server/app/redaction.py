"""Redaction engine: pure functions, no I/O.

Patterns run in a fixed order (JWT, EMAIL, CREDIT_CARD, IPV4) so a longer
token is replaced — and its placeholder, which contains no digits, dots or
@, becomes un-matchable — before a shorter pattern could match inside it.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class RedactionType(str, Enum):
    """Kinds of sensitive data. The value is used in placeholders and counts."""

    JWT = "JWT"
    EMAIL = "EMAIL"
    CREDIT_CARD = "CREDIT_CARD"
    IPV4 = "IPV4"

    @property
    def placeholder(self) -> str:
        return f"[REDACTED_{self.value}]"   # e.g. "[REDACTED_EMAIL]"


@dataclass
class RedactionResult:
    text: str
    counts: dict[str, int] = field(default_factory=dict)


# ---------- validators: confirm a regex match is real ----------

def _is_valid_jwt(match: re.Match[str]) -> bool:
    header_b64 = match.group(0).split(".", 1)[0]
    padded = header_b64 + "=" * (-len(header_b64) % 4)
    try:
        header = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return False
    return isinstance(header, dict) and "alg" in header


def _is_valid_email(match: re.Match[str]) -> bool:
    domain = match.group(0).rsplit("@", 1)[1]
    tld = domain.rsplit(".", 1)[-1]
    return tld.isalpha() and len(tld) >= 2


def _is_valid_ipv4(match: re.Match[str]) -> bool:
    return all(0 <= int(part) <= 255 for part in match.group(0).split("."))


def _luhn_ok(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


# ---------- credit cards: find the card inside a run of digit groups ----------

def _redact_card_run(run: str, counts: dict[str, int]) -> str:
    """Replace the longest Luhn-valid span of 13-19 digits, keeping extra digits.

    "4111 1111 1111 1111 123" -> "[REDACTED_CREDIT_CARD] 123"
    """
    parts = re.split(r"([ -])", run)   # "4111 1111 123" -> ["4111", " ", "1111", " ", "123"]
    groups = parts[0::2]               # ["4111", "1111", "123"]
    seps = parts[1::2]                 # [" ", " "]

    out: list[str] = []
    i = 0
    while i < len(groups):
        best_end = None
        digits = ""
        for j in range(i, len(groups)):          # extend the span one group at a time
            digits += groups[j]
            if len(digits) > 19:                  # too long to be a card
                break
            if len(digits) >= 13 and _luhn_ok(digits):
                best_end = j                      # longest valid span so far

        if best_end is None:                      # no card starts here: keep this group
            out.append(groups[i])
            last = i
        else:                                     # card found: replace the whole span
            card = RedactionType.CREDIT_CARD
            counts[card.value] = counts.get(card.value, 0) + 1
            out.append(card.placeholder)
            last = best_end

        if last < len(seps):                      # keep the separator after it
            out.append(seps[last])
        i = last + 1

    return "".join(out)


# ---------- generic replacement for JWT, EMAIL, IPV4 ----------

def _replace(
    match: re.Match[str],
    kind: RedactionType,
    validator: Callable[[re.Match[str]], bool],
    counts: dict[str, int],
) -> str:
    if not validator(match):
        return match.group(0)
    counts[kind.value] = counts.get(kind.value, 0) + 1
    return kind.placeholder


# A replacer takes one regex match plus the counts map, and returns the text
# to put in place of that match.
Replacer = Callable[[re.Match[str], dict[str, int]], str]

# Order matters: JWT first so its dots and digits are gone before the
# looser patterns run. Every entry is (regex, replacer), handled the same way.
_PATTERNS: list[tuple[re.Pattern[str], Replacer]] = [
    (
        re.compile(r"\beyJ[\w-]+\.eyJ[\w-]+\.[\w-]+"),
        lambda m, counts: _replace(m, RedactionType.JWT, _is_valid_jwt, counts),
    ),
    (
        re.compile(r"[^\s@()<>\[\]\"',;:]+@[\w-]+(?:\.[\w-]+)+\b"),
        lambda m, counts: _replace(m, RedactionType.EMAIL, _is_valid_email, counts),
    ),
    (
        re.compile(r"(?<!\w)\d+(?:[ -]\d+)*(?!\w)"),
        lambda m, counts: _redact_card_run(m.group(0), counts),
    ),
    (
        re.compile(r"(?<![\d.])\b\d{1,3}(?:\.\d{1,3}){3}\b(?!\.\d)"),
        lambda m, counts: _replace(m, RedactionType.IPV4, _is_valid_ipv4, counts),
    ),
]


def redact(text: str) -> RedactionResult:
    counts: dict[str, int] = {}
    for pattern, replacer in _PATTERNS:
        text = pattern.sub(lambda m: replacer(m, counts), text)
    return RedactionResult(text=text, counts=counts)