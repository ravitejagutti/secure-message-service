import pytest

from server.app.redaction import redact

pytestmark = pytest.mark.unit

JWT_HEADER = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
JWT_PAYLOAD = "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IlRlc3QgVXNlciJ9"
JWT = f"{JWT_HEADER}.{JWT_PAYLOAD}.dummySignature123-abc"

VISA = "4111 1111 1111 1111"
MASTERCARD = "5500-0000-0000-0004"
AMEX = "340000000000009"


# Input:    "Here is a token <JWT> in the middle of a sentence."
# Expected: "Here is a token [REDACTED_JWT] in the middle of a sentence."
#           counts == {"JWT": 1}
def test_jwt_in_sentence_is_redacted():
    text = f"Here is a token {JWT} in the middle of a sentence."
    result = redact(text)
    assert "[REDACTED_JWT]" in result.text
    assert JWT not in result.text
    assert result.text == "Here is a token [REDACTED_JWT] in the middle of a sentence."
    assert result.counts == {"JWT": 1}


# Input:    "Not a real token: <header>.<payload>"   (only 2 parts, a JWT has 3)
# Expected: text unchanged, counts == {}
def test_two_part_jwt_lookalike_is_not_redacted():
    text = f"Not a real token: {JWT_HEADER}.{JWT_PAYLOAD}"
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# Input:    "Contact: alice@example.com"  /  "Contact: a.b+tag@sub.example.co.in"
# Expected: "Contact: [REDACTED_EMAIL]", counts == {"EMAIL": 1}
@pytest.mark.parametrize("email", ["alice@example.com", "a.b+tag@sub.example.co.in"])
def test_valid_emails_are_redacted(email):
    result = redact(f"Contact: {email}")
    assert "[REDACTED_EMAIL]" in result.text
    assert email not in result.text
    assert result.counts == {"EMAIL": 1}


# Input:    "Ping alice@localhost for access"  (no dotted domain)
#           "Follow @handle for updates"       (nothing before the @)
# Expected: text unchanged, counts == {}
@pytest.mark.parametrize(
    "text",
    ["Ping alice@localhost for access", "Follow @handle for updates"],
)
def test_non_emails_are_not_redacted(text):
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# Input:    "Connect to 192.168.0.1 now"  (also 0.0.0.0 and 255.255.255.255)
# Expected: "Connect to [REDACTED_IPV4] now", counts == {"IPV4": 1}
@pytest.mark.parametrize("ip", ["192.168.0.1", "0.0.0.0", "255.255.255.255"])
def test_valid_ipv4_addresses_are_redacted(ip):
    result = redact(f"Connect to {ip} now")
    assert "[REDACTED_IPV4]" in result.text
    assert ip not in result.text
    assert result.counts == {"IPV4": 1}


# Input:    "Server 256.1.1.1 is unreachable"     (octet > 255)
#           "Upgrade to release 1.2.3 today"      (only 3 parts)
#           "Running version 1.2.3.4.5 in prod"   (5 parts)
# Expected: text unchanged, counts == {}
@pytest.mark.parametrize(
    "text",
    [
        "Server 256.1.1.1 is unreachable",
        "Upgrade to release 1.2.3 today",
        "Running version 1.2.3.4.5 in prod",
    ],
)
def test_invalid_ipv4_addresses_are_not_redacted(text):
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# Input:    "Please charge 4111 1111 1111 1111 for the order"   (Visa, with spaces)
#           "Please charge 5500-0000-0000-0004 for the order"   (Mastercard, with dashes)
#           "Please charge 340000000000009 for the order"       (Amex, no separators)
# Expected: "Please charge [REDACTED_CREDIT_CARD] for the order", counts == {"CREDIT_CARD": 1}
@pytest.mark.parametrize("card", [VISA, MASTERCARD, AMEX])
def test_card_numbers_are_redacted(card):
    result = redact(f"Please charge {card} for the order")
    assert result.text == "Please charge [REDACTED_CREDIT_CARD] for the order"
    assert result.counts == {"CREDIT_CARD": 1}


# Input:    "Tracking number 4111111111111112 is on its way"  (card-like, fails Luhn)
# Expected: text unchanged, counts == {}
def test_number_failing_luhn_check_is_not_redacted():
    text = "Tracking number 4111111111111112 is on its way"  # last digit flipped
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# Input:    "Token <JWT>, email alice@example.com, card 4111 1111 1111 1111, ip 192.168.0.1"
# Expected: all four placeholders, none of the raw values,
#           counts == {"JWT": 1, "EMAIL": 1, "CREDIT_CARD": 1, "IPV4": 1}
def test_all_four_types_in_one_message_are_redacted():
    text = (
        f"Token {JWT}, email alice@example.com, "
        f"card {VISA}, ip 192.168.0.1"
    )
    result = redact(text)
    assert result.counts == {"JWT": 1, "EMAIL": 1, "CREDIT_CARD": 1, "IPV4": 1}
    assert JWT not in result.text
    assert "alice@example.com" not in result.text
    assert VISA not in result.text
    assert "192.168.0.1" not in result.text
    for placeholder in (
        "[REDACTED_JWT]",
        "[REDACTED_EMAIL]",
        "[REDACTED_CREDIT_CARD]",
        "[REDACTED_IPV4]",
    ):
        assert placeholder in result.text


# Input:    "alice@example.com wrote to alice@example.com"
# Expected: "[REDACTED_EMAIL] wrote to [REDACTED_EMAIL]", counts == {"EMAIL": 2}
def test_repeated_email_is_redacted_and_counted_twice():
    result = redact("alice@example.com wrote to alice@example.com")
    assert result.counts == {"EMAIL": 2}
    assert "alice@example.com" not in result.text


# Input:    ""  /  "no sensitive data here"  /  "unicode: café, naïve, 日本語"
# Expected: text unchanged, counts == {}
@pytest.mark.parametrize(
    "text",
    ["", "no sensitive data here", "unicode: café, naïve, 日本語"],
)
def test_text_without_sensitive_data_is_unchanged(text):
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# ---------- regressions: card numbers next to other digits ----------
# A greedy match used to swallow the extra digits, fail Luhn on the whole run
# and leave the card in clear text. The card must be found inside the run.

# Input:    "My card is 4111 1111 1111 1111 123 for CVV"
# Expected: "My card is [REDACTED_CREDIT_CARD] 123 for CVV"
# Input:    "Card 4111111111111111 12/27 expires soon"
# Expected: "Card [REDACTED_CREDIT_CARD] 12/27 expires soon"
# Input:    "Order ref 12 4111 1111 1111 1111 was charged"
# Expected: "Order ref 12 [REDACTED_CREDIT_CARD] was charged"
# counts == {"CREDIT_CARD": 1} in each case
@pytest.mark.parametrize(
    "text, expected",
    [
        (   # card + CVV
            "My card is 4111 1111 1111 1111 123 for CVV",
            "My card is [REDACTED_CREDIT_CARD] 123 for CVV",
        ),
        (   # card + expiry
            "Card 4111111111111111 12/27 expires soon",
            "Card [REDACTED_CREDIT_CARD] 12/27 expires soon",
        ),
        (   # number before the card
            "Order ref 12 4111 1111 1111 1111 was charged",
            "Order ref 12 [REDACTED_CREDIT_CARD] was charged",
        ),
    ],
)
def test_card_next_to_other_digits_is_redacted(text, expected):
    result = redact(text)
    assert result.text == expected
    assert result.counts == {"CREDIT_CARD": 1}


# A number in front of a card can form a Luhn-valid span that ends inside the
# card. Taking only that span used to leave the rest of the card in clear text.
# Input:    "Ref 12 4088 9957 9032 8924 99 paid"     ("12 4088 9957 9032" also passes Luhn)
# Expected: "Ref [REDACTED_CREDIT_CARD] 99 paid"
# Input:    "Ref 123456789 4831 0122 2834 5981 paid" ("123456789 4831" also passes Luhn)
# Expected: "Ref [REDACTED_CREDIT_CARD] paid"
# counts == {"CREDIT_CARD": 1} in each case; no digit of the card remains
@pytest.mark.parametrize(
    "text, expected, card",
    [
        (
            "Ref 12 4088 9957 9032 8924 99 paid",
            "Ref [REDACTED_CREDIT_CARD] 99 paid",
            "4088 9957 9032 8924",
        ),
        (
            "Ref 123456789 4831 0122 2834 5981 paid",
            "Ref [REDACTED_CREDIT_CARD] paid",
            "4831 0122 2834 5981",
        ),
    ],
)
def test_card_overlapping_a_valid_span_before_it_is_fully_redacted(text, expected, card):
    result = redact(text)
    assert result.text == expected
    assert result.counts == {"CREDIT_CARD": 1}
    for group in card.split():
        assert group not in result.text


# Input:    "Split it across 4111 1111 1111 1111 5500 0000 0000 0004 please"
# Expected: "Split it across [REDACTED_CREDIT_CARD] [REDACTED_CREDIT_CARD] please"
#           counts == {"CREDIT_CARD": 2}
def test_two_adjacent_cards_are_both_redacted():
    result = redact(f"Split it across {VISA} {MASTERCARD.replace('-', ' ')} please")
    assert result.text == (
        "Split it across [REDACTED_CREDIT_CARD] [REDACTED_CREDIT_CARD] please"
    )
    assert result.counts == {"CREDIT_CARD": 2}


# Input:    "Call me on +91 98765 43210 after lunch"
#           "The meeting is on 2026-10-22 at noon"
#           "Your order 1234567890123456 has shipped"   (fails Luhn)
# Expected: text unchanged, counts == {}
@pytest.mark.parametrize(
    "text",
    [
        "Call me on +91 98765 43210 after lunch",
        "The meeting is on 2026-10-22 at noon",
        "Your order 1234567890123456 has shipped",
    ],
)
def test_phone_numbers_dates_and_order_numbers_are_not_redacted(text):
    result = redact(text)
    assert result.text == text
    assert result.counts == {}


# ---------- email: permissive before the @, strict after it ----------

# Input:    "Send the report to ravi!k#99@example.com by Friday"
# Expected: "Send the report to [REDACTED_EMAIL] by Friday"  (no part of the address left)
def test_email_with_unusual_characters_is_fully_redacted():
    result = redact("Send the report to ravi!k#99@example.com by Friday")
    assert result.text == "Send the report to [REDACTED_EMAIL] by Friday"


# Input:    "Contact Ravi (ravi@example.com) today"
# Expected: "Contact Ravi ([REDACTED_EMAIL]) today"
# Input:    "From: Ravi <ravi@example.com>"
# Expected: "From: Ravi <[REDACTED_EMAIL]>"
# Input:    "Please write to ravi@example.com."
# Expected: "Please write to [REDACTED_EMAIL]."
@pytest.mark.parametrize(
    "text, expected",
    [
        ("Contact Ravi (ravi@example.com) today", "Contact Ravi ([REDACTED_EMAIL]) today"),
        ("From: Ravi <ravi@example.com>", "From: Ravi <[REDACTED_EMAIL]>"),
        ("Please write to ravi@example.com.", "Please write to [REDACTED_EMAIL]."),
    ],
)
def test_punctuation_around_email_is_kept(text, expected):
    assert redact(text).text == expected


# ---------- IPv4 edge cases ----------

# Input:    "The app runs on 10.0.0.1:8080 now"
# Expected: "The app runs on [REDACTED_IPV4]:8080 now"
def test_ip_with_port_keeps_the_port():
    result = redact("The app runs on 10.0.0.1:8080 now")
    assert result.text == "The app runs on [REDACTED_IPV4]:8080 now"


# Input:    "Log in as user@192.168.1.1 over SSH"  (not an email: no letter TLD)
# Expected: "Log in as user@[REDACTED_IPV4] over SSH"
def test_email_with_ip_domain_has_only_the_ip_redacted():
    # Not a valid email (no letter TLD), but the IP inside it is still hidden.
    result = redact("Log in as user@192.168.1.1 over SSH")
    assert result.text == "Log in as user@[REDACTED_IPV4] over SSH"


# ---------- JWT validation ----------

# Input:    "Debug value eyJ...eyJ...sig from the logs", where the first part
#           decodes to {"notaheader": 1} (no "alg", so not a real JWT header)
# Expected: text unchanged
def test_jwt_lookalike_without_alg_header_is_not_redacted():
    text = "Debug value eyJub3RhaGVhZGVyIjoxfQ.eyJzdWIiOiJ4In0.sig from the logs"
    assert redact(text).text == text
