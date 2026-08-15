# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.environ.get("DARITH_BASE_URL", "http://127.0.0.1:8000")
USERNAME = os.environ.get("DARITH_UI_USER", "ui_check")
PASSWORD = os.environ.get("DARITH_UI_PASSWORD", "test-pass-123")
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/snap/bin/chromium")
OUTPUT_DIR = Path(os.environ.get("DARITH_SCREENSHOT_DIR", "/tmp/darith-ui"))


def assert_no_horizontal_overflow(page):
    overflowing = page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    if overflowing:
        raise AssertionError("The page has horizontal overflow.")


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    console_errors = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=CHROMIUM_PATH,
            headless=True,
            args=["--no-sandbox"],
        )
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.get_by_text("No bank credentials").wait_for()
        page.get_by_text("Limited admin view").wait_for()
        page.get_by_role("heading", name="From the Daric", exact=True).wait_for()
        page.locator('img[src*="daric-coin.jpg"]').wait_for()
        page.get_by_role("link", name="Start free").first.wait_for()
        page.get_by_text("45-day hosted trial").wait_for()
        page.get_by_role("link", name="Try Darith free for 45 days").wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "landing-desktop.png", full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        page.get_by_role("link", name="Start free").first.wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "landing-mobile.png", full_page=True)

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
        page.screenshot(path=OUTPUT_DIR / "login-desktop.png", full_page=True)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard/**")
        page.get_by_text("Free to spend this month").wait_for()
        page.get_by_text("status", exact=False).first.wait_for()
        app_shell = page.locator(".app-shell")
        if app_shell.get_attribute("data-values-hidden") == "true":
            page.locator(".visibility-toggle").click()
            page.wait_for_load_state("networkidle")
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "dashboard-desktop.png", full_page=True)
        page.locator(".visibility-toggle").click()
        page.wait_for_load_state("networkidle")
        if app_shell.get_attribute("data-values-hidden") != "true":
            raise AssertionError("Dashboard amount masking was not saved.")
        if page.locator(".budget-main strong").inner_text() != "******":
            raise AssertionError("The main dashboard amount was not masked.")
        page.reload(wait_until="networkidle")
        if app_shell.get_attribute("data-values-hidden") != "true":
            raise AssertionError("Dashboard amount masking did not persist.")
        page.screenshot(path=OUTPUT_DIR / "dashboard-hidden-desktop.png", full_page=True)
        page.locator(".visibility-toggle").click()
        page.wait_for_load_state("networkidle")

        page.locator('.budget-tools [data-dialog-open="dashboard-animation-edit"]').click()
        settings_dialog = page.locator("#dashboard-animation-edit")
        settings_dialog.wait_for()
        if settings_dialog.locator('option[value="IRT"]').count() != 1:
            raise AssertionError("Iranian Toman is missing from display currencies.")
        settings_dialog.get_by_role("tab", name="Behavior").click()
        settings_dialog.locator('select[name="transaction_deletion_mode"]').wait_for()
        settings_dialog.get_by_role("tab", name="Security").click()
        settings_dialog.locator('select[name="lock_timeout_minutes"]').wait_for()
        settings_dialog.get_by_role("button", name="Add passkey").wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "settings-desktop.png", full_page=True)
        settings_dialog.get_by_role("button", name="Close").click()

        page.locator('.sidebar [data-dialog-open="feedback-dialog"]').click()
        feedback_dialog = page.locator("#feedback-dialog")
        feedback_dialog.locator('textarea[name="message"]').wait_for()
        feedback_dialog.get_by_role("button", name="Close").click()

        page.locator('.sidebar [data-tab-target="accounts"]').click()
        page.locator('[data-tab-panel="accounts"] .page-heading [data-dialog-open="account-create"]').click()
        account_dialog = page.locator("#account-create")
        account_dialog.locator('input[name="include_in_budget"]').wait_for()
        if not account_dialog.locator('input[name="include_in_budget"]').is_checked():
            raise AssertionError("New bank accounts should be included in the budget by default.")
        page.screenshot(path=OUTPUT_DIR / "account-dialog-desktop.png", full_page=True)
        account_dialog.get_by_role("button", name="Close").click()
        page.locator('.sidebar [data-tab-target="overview"]').click()

        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        page.locator(".mobile-nav").wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "dashboard-mobile.png", full_page=True)
        page.locator(".mobile-overflow summary").click()
        page.locator(".mobile-menu").get_by_role("button", name="Settings").click()
        settings_dialog.wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "settings-mobile.png", full_page=True)
        settings_dialog.get_by_role("button", name="Close").click()
        page.locator(".mobile-overflow").evaluate("element => element.open = false")

        page.click('.mobile-nav [data-tab-target="plans"]')
        page.locator('[data-tab-panel="plans"] h3', has_text="Recurring income").wait_for()
        page.screenshot(path=OUTPUT_DIR / "plans-mobile.png", full_page=True)
        page.locator(".mobile-overflow summary").click()
        page.locator(".mobile-menu", has_text="Categories").get_by_role(
            "button", name="Categories"
        ).click()
        page.locator('[data-tab-panel="categories"] h2', has_text="Custom categories").wait_for()
        assert_no_horizontal_overflow(page)
        browser.close()

    if console_errors:
        raise AssertionError(f"Browser console errors: {console_errors}")
    print(f"UI smoke test passed. Screenshots: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
