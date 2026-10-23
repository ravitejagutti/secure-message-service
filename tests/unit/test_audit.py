import pytest

from server.app.audit import format_event, redaction_summary

pytestmark = pytest.mark.unit


# Input:    event "message.deleted", id=42, by="alice"
# Expected: "message.deleted id=42 by=alice"
def test_event_is_one_line_of_key_value_pairs():
    assert format_event("message.deleted", id=42, by="alice") == "message.deleted id=42 by=alice"


# Input:    a route containing a newline and a fake second entry
# Expected: unsafe characters become "_", so the value can't start a new log line
def test_request_values_cannot_inject_log_lines():
    line = format_event("auth.failed", route="/api\n2026-01-01T00:00:00Z AUDIT message.deleted id=1")
    assert "\n" not in line
    assert line == "auth.failed route=/api_2026-01-01T00:00:00Z_AUDIT_message.deleted_id=1"


# Input:    {"IPV4": 2, "EMAIL": 1}  /  {}
# Expected: "EMAIL=1,IPV4=2" (sorted)  /  "none"
def test_redaction_summary():
    assert redaction_summary({"IPV4": 2, "EMAIL": 1}) == "EMAIL=1,IPV4=2"
    assert redaction_summary({}) == "none"
