# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "darith.settings")

import django

django.setup()

from django.contrib.auth.models import User
from playwright.sync_api import sync_playwright

from web.models import BankAccount


BASE_URL = os.environ.get("DARITH_BASE_URL", "http://127.0.0.1:8012")
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/snap/bin/chromium")
USERNAME = "darith_passkey_smoke"
PASSWORD = "passkey-smoke-only-4286"


def prepare_user():
    User.objects.filter(username=USERNAME).delete()
    user = User.objects.create_user(
        username=USERNAME,
        email="passkey-smoke@darith.local",
        password=PASSWORD,
    )
    BankAccount.objects.create(user=user, name="Main", balance="500.00")


def main():
    prepare_user()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=CHROMIUM_PATH,
                headless=True,
                args=["--no-sandbox"],
            )
            context = browser.new_context()
            context.credentials.install()
            page = context.new_page()

            page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
            page.fill("#username", USERNAME)
            page.fill("#password", PASSWORD)
            page.click(".auth-submit")
            page.wait_for_url("**/dashboard/**")

            settings_button = page.locator(
                '.budget-tools [data-dialog-open="dashboard-animation-edit"]'
            )
            settings_button.click()
            settings = page.locator("#dashboard-animation-edit")
            settings.locator("#passkey-name").fill("Virtual device")
            settings.get_by_role("button", name="Add passkey").click()
            page.wait_for_load_state("networkidle")
            settings_button.click()
            settings.get_by_text("Virtual device", exact=True).wait_for()
            settings.locator('select[name="lock_timeout_minutes"]').select_option("1")
            settings.get_by_role("button", name="Save lock settings").click()
            page.wait_for_load_state("networkidle")
            result = page.evaluate(
                """async () => {
                    const token = document.querySelector("input[name='csrfmiddlewaretoken']").value;
                    const response = await fetch('/lock/now/', {
                        method: 'POST', headers: {'X-CSRFToken': token}
                    });
                    return response.ok;
                }"""
            )
            if not result:
                raise AssertionError("The lock endpoint rejected the request.")
            page.goto(f"{BASE_URL}/lock/", wait_until="networkidle")
            page.get_by_role(
                "button", name="Use passkey / fingerprint / Face ID"
            ).click()
            page.wait_for_url("**/dashboard/**")

            page.locator('.sidebar form[action="/logout/"] button').click()
            page.wait_for_url("**/login/")
            page.get_by_role("button", name="Use a passkey").click()
            page.wait_for_url("**/dashboard/**")
            browser.close()
    finally:
        User.objects.filter(username=USERNAME).delete()

    print("Passkey enrollment, unlock, and passwordless sign-in passed.")


if __name__ == "__main__":
    main()
