# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.
import os
import subprocess
import sys
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "darith.settings")

import django

django.setup()

from django.contrib.auth.models import User
from playwright.sync_api import sync_playwright

from web.models import BankAccount, BudgetPreference


BASE_URL = os.environ.get("DARITH_BASE_URL", "http://127.0.0.1:8011")
CHROMIUM_PATH = os.environ.get("CHROMIUM_PATH", "/snap/bin/chromium")
STATIC_IMAGES = BASE_DIR / "web/static/images"
USERNAME = "darith_demo_capture"
PASSWORD = "demo-capture-only-4286"


def prepare_demo_user():
    User.objects.filter(username=USERNAME).delete()
    user = User.objects.create_user(
        username=USERNAME,
        email="demo-capture@darith.local",
        password=PASSWORD,
    )
    BankAccount.objects.create(
        user=user,
        name="Everyday account",
        balance=Decimal("600.00"),
    )
    BudgetPreference.objects.create(
        user=user,
        expected_daily_expense=Decimal("10.00"),
    )


def add_step_label(page, text):
    page.evaluate(
        """label => {
            let element = document.getElementById('demo-step-label');
            if (!element) {
                element = document.createElement('div');
                element.id = 'demo-step-label';
                Object.assign(element.style, {
                    position: 'fixed', top: '14px', left: '50%', zIndex: '999',
                    transform: 'translateX(-50%)', padding: '10px 16px',
                    borderRadius: '6px', color: '#fff', background: '#071a3a',
                    boxShadow: '0 8px 24px rgba(0,0,0,.24)', fontSize: '13px',
                    fontWeight: '750', letterSpacing: '0'
                });
                document.body.appendChild(element);
            }
            element.textContent = label;
        }""",
        text,
    )


def capture(page, frame_dir, frame_number, label):
    add_step_label(page, label)
    page.screenshot(path=frame_dir / f"frame-{frame_number:02d}.png")


def main():
    prepare_demo_user()
    STATIC_IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="darith-demo-") as directory:
        frame_dir = Path(directory)
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=CHROMIUM_PATH,
                headless=True,
                args=["--no-sandbox"],
            )
            page = browser.new_page(viewport={"width": 1200, "height": 760})
            page.goto(f"{BASE_URL}/login/", wait_until="networkidle")
            page.fill("#username", USERNAME)
            page.fill("#password", PASSWORD)
            page.click(".auth-submit")
            page.wait_for_url("**/dashboard/**")
            page.get_by_text("Free to spend this month").wait_for()
            capture(page, frame_dir, 0, "Start with your current balance")

            page.get_by_role("button", name="+ Income").click()
            income_dialog = page.locator("#income-create")
            income_dialog.locator('input[name="text"]').fill("Salary")
            income_dialog.locator('input[name="amount"]').fill("1800")
            income_dialog.locator('input[name="date"]').fill(date.today().isoformat())
            income_dialog.locator('select[name="bank_account"]').select_option(label="Everyday account - 600.00")
            capture(page, frame_dir, 1, "1. Add income")
            income_dialog.get_by_role("button", name="Add income").click()
            page.wait_for_url("**/dashboard/?tab=transactions")
            page.locator(
                '[data-tab-panel="transactions"] .transaction-copy strong',
                has_text="Salary",
            ).first.wait_for()
            capture(page, frame_dir, 2, "Income updates the account")

            page.get_by_role("button", name="+ Expense").first.click()
            expense_dialog = page.locator("#expense-create")
            expense_dialog.locator('input[name="text"]').fill("Rent")
            expense_dialog.locator('input[name="amount"]').fill("700")
            expense_dialog.locator('input[name="date"]').fill(date.today().isoformat())
            expense_dialog.locator('select[name="bank_account"]').select_option(
                label="Everyday account - 2400.00"
            )
            capture(page, frame_dir, 3, "2. Add an expense")
            expense_dialog.get_by_role("button", name="Add expense").click()
            page.wait_for_url("**/dashboard/?tab=transactions")
            page.locator(
                '[data-tab-panel="transactions"] .transaction-copy strong',
                has_text="Rent",
            ).first.wait_for()
            capture(page, frame_dir, 4, "Spending updates the same ledger")

            page.locator('.sidebar [data-tab-target="overview"]').click()
            page.get_by_text("Free to spend this month").wait_for()
            capture(page, frame_dir, 5, "3. See what is free to spend")

            page.locator("#demo-step-label").evaluate("element => element.remove()")
            page.locator(".message-stack").evaluate("element => element.remove()")
            page.set_viewport_size({"width": 1440, "height": 1000})
            page.screenshot(path=STATIC_IMAGES / "dashboard-preview.png")
            page.set_viewport_size({"width": 390, "height": 844})
            page.reload(wait_until="networkidle")
            page.screenshot(path=STATIC_IMAGES / "dashboard-mobile.png")
            browser.close()

        frames = [frame_dir / f"frame-{number:02d}.png" for number in range(6)]
        command = ["convert"]
        delays = [130, 110, 110, 110, 110, 180]
        for delay, frame in zip(delays, frames):
            command.extend(["-delay", str(delay), str(frame)])
        command.extend(
            [
                "-resize",
                "900x570",
                "-colors",
                "128",
                "-layers",
                "Optimize",
                "-loop",
                "0",
                str(STATIC_IMAGES / "darith-demo.gif"),
            ]
        )
        subprocess.run(command, check=True)

    User.objects.filter(username=USERNAME).delete()
    print("Captured dashboard-preview.png, dashboard-mobile.png, and darith-demo.gif")


if __name__ == "__main__":
    main()
