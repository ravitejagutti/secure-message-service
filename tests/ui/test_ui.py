"""Playwright tests: the web page shows redacted values, never raw ones.

Messages are seeded through the API, then checked in a real browser.

TLS note: Chromium can't be pointed at a single CA file the way httpx can, so
the browser context ignores certificate errors. TLS itself is verified with
the pinned cert in the API suite
(test_self_signed_cert_is_trusted_only_when_pinned).

Pages come from pytest-playwright's own `page` fixture, so its options apply:
tracing and screenshots on failure (set in pytest.ini), --headed, --slowmo.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser, Page, expect
from playwright.sync_api import Error as PlaywrightError

from tests.sample_data import PLACEHOLDERS, RAW_VALUES, sensitive_message

pytestmark = pytest.mark.ui


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, server_url, username, password):
    """Settings for every browser context pytest-playwright creates for a test."""
    return {
        **browser_context_args,
        "base_url": server_url,                  # page.goto("/") -> https://localhost:8443/
        "http_credentials": {"username": username, "password": password},  # answers the login prompt
        "ignore_https_errors": True,             # our self-signed certificate
    }


@pytest.fixture
def logged_in_page(page: Page) -> Page:
    """A fresh, logged-in tab in its own context (like a new incognito window).

    pytest-playwright creates and closes it, and records a trace if the test fails.
    """
    return page


def _row(page: Page, message_id: int):
    return page.locator(f'[data-testid="message-row"][data-message-id="{message_id}"]')


# Setup:    create a message with a JWT, email, IPv4 and card via the API
# Action:   log in and open the web page
# Expected: its row shows all four placeholders; no raw value anywhere in the page
def test_page_shows_placeholders_not_raw_values(logged_in_page, create_message, unique_tag):
    message = create_message(sensitive_message(unique_tag))

    logged_in_page.goto("/")
    row = _row(logged_in_page, message["id"])
    expect(row).to_have_count(1)

    content = row.get_by_test_id("message-content")
    for placeholder in PLACEHOLDERS:
        expect(content).to_contain_text(placeholder)

    page_text = logged_in_page.content()
    for raw in RAW_VALUES:
        assert raw not in page_text


# Setup:    create "<script>window.__xss = 1</script><b>bold</b>"
# Expected: the cell shows that text literally; the script never runs,
#           no <b> element is rendered, no dialog appears
def test_html_in_messages_is_shown_as_text(logged_in_page, create_message, unique_tag):
    payload = f"{unique_tag} <script>window.__xss = 1</script><b>bold</b>"
    message = create_message(payload)

    dialogs: list[str] = []
    logged_in_page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
    logged_in_page.goto("/")

    content = _row(logged_in_page, message["id"]).get_by_test_id("message-content")
    expect(content).to_have_text(payload)                 # shown as literal text
    assert logged_in_page.evaluate("window.__xss") is None  # script never ran
    expect(content.locator("b")).to_have_count(0)         # tags not rendered
    assert dialogs == []


# Setup:    create a message, see its row, delete it via the API, reload
# Expected: the row is gone
def test_deleted_message_disappears_from_page(logged_in_page, api, create_message, unique_tag):
    message = create_message(f"{unique_tag} to be deleted")

    logged_in_page.goto("/")
    expect(_row(logged_in_page, message["id"])).to_have_count(1)

    assert api.delete(f"/api/messages/{message['id']}").status_code == 204
    logged_in_page.reload()
    expect(_row(logged_in_page, message["id"])).to_have_count(0)


# Action:   open the web page with no credentials
# Expected: refused. Headless Chromium returns the 401 response; a visible
#           (--headed) one cancels its login prompt instead, which Playwright
#           reports as ERR_INVALID_AUTH_CREDENTIALS. Either way, no page.
def test_page_without_login_is_refused(browser: Browser, server_url):
    context = browser.new_context(ignore_https_errors=True)
    try:
        try:
            response = context.new_page().goto(f"{server_url}/")
        except PlaywrightError as exc:
            assert "ERR_INVALID_AUTH_CREDENTIALS" in str(exc)
        else:
            assert response is not None and response.status == 401
    finally:
        context.close()
