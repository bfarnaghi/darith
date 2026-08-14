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
        page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
        page.screenshot(path=OUTPUT_DIR / "login-desktop.png", full_page=True)
        page.fill("#username", USERNAME)
        page.fill("#password", PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url("**/dashboard/**")
        page.get_by_text("Free to spend this month").wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "dashboard-desktop.png", full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.reload(wait_until="networkidle")
        page.locator(".mobile-nav").wait_for()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=OUTPUT_DIR / "dashboard-mobile.png", full_page=True)

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
