"""Shared UI test setup: browser settings, a logged-in page, and a screenshot in
the Allure report when a UI test fails. Applies to every test file in tests/ui."""

from __future__ import annotations

import allure
import pytest
from playwright.sync_api import Page


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """After each UI test body runs: if it failed, attach what the browser showed.

    Runs for tests in this folder only. The screenshot is taken while the page is
    still open, so it shows the moment of failure; the page URL tells where the
    browser was. Passing tests attach nothing. (The full Playwright trace is
    still saved as a file in the run folder, under playwright/.)
    """
    outcome = yield
    report = outcome.get_result()
    if report.when != "call" or not report.failed:
        return
    page = item.funcargs.get("logged_in_page") or item.funcargs.get("page")
    if page is None:                 # e.g. a test that drives the browser directly
        return
    name = item.name                 # e.g. "test_page_shows_placeholders_not_raw_values[chromium]"
    try:
        allure.attach(page.screenshot(full_page=True), name=f"{name} - screenshot at failure",
                      attachment_type=allure.attachment_type.PNG)
        allure.attach(page.url, name=f"{name} - page URL", attachment_type=allure.attachment_type.TEXT)
    except Exception as exc:         # never let the report helper hide the real failure
        allure.attach(f"Could not capture the page: {exc}", name=f"{name} - screenshot error",
                      attachment_type=allure.attachment_type.TEXT)
