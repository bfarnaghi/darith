<p align="center">
  <img src="web/static/images/logo.png" alt="Darith logo" width="180">
</p>

# Darith

Darith is a multilingual personal-finance app for mobile and desktop. It tracks accounts, flexible plans, and saving goals, and shows how much is safe to spend.

**Website:** [https://darith.app](https://darith.app)

## Run locally

~~~bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
~~~

Open `http://127.0.0.1:8000`, create a user account, and sign in.

## How to use it

1. Add each real bank account and its current balance under **Accounts**. Darith shows when included balances were last updated. Saving an account also confirms that its balance is current.
2. Set **Daily spending** and an optional **Emergency buffer** in **Settings → Planning**.
3. Add future income and expenses under **Plans**. Each plan can happen **Once**, **Daily**, **Weekly**, or **Monthly**.
4. When a planned date arrives, Darith asks what happened. Mark it done to update the real account, move only that occurrence to another date, change its amount, or skip only that occurrence. Darith is passive: it never changes a balance just because a planned date passed.
5. Record manual income and expenses when they have already happened. Their selected account balance updates immediately.
6. Use **Transfer** to move money between banks, from a bank to a goal, or from a goal back to a bank.
7. Create an ongoing saving goal with a monthly amount, or enter a target amount and target date. When a saving date arrives, confirm it, change only that month's amount/date, or skip that month.
8. Check **Safe to spend today** to see how much extra money you can spend now while keeping the rest of the current month on track.
9. If enabled, use **Money by day** on Overview to check future dates. **Months to show** changes only how far the slider goes; it does not change today's blue-card result.
10. Use **Can I spend more?** to enter an extra amount and a number of days. If needed, Darith suggests a temporary daily-spending amount. Choose **Add to my plan** to add the one-time expense and the temporary daily-spending change.
11. Use **Export CSV** to download your records.
12. Use **Settings → Appearance** for language, theme, currency, profile picture, and private status GIFs. Currency changes labels only and does not convert stored amounts.
13. Use **Settings → Security** for a passkey, Darith PIN, and auto lock.
14. Use **Settings → Account** to change your username or password, or permanently delete your account.

Planning settings:

- **Daily spending**: the amount you normally expect to spend each day.
- **Emergency buffer**: money Darith always keeps aside. Default: `0`.
- **Months to show**: show `1`, `2`, or `3` future months in Money by day. Default: `1`.
- **Show money timeline**: show or hide the day-by-day slider. Default: on.

Darith is passive. The legacy `process_scheduled_transactions` command now only reports items waiting for confirmation and does not change balances.

## Security

Production mode requires PostgreSQL with TLS and refuses insecure defaults. Darith also uses Argon2 password and PIN hashing, WebAuthn passkeys, inactivity locking, secure cookies, HTTPS redirects, browser security headers, private authenticated profile-picture/GIF delivery, and encrypted database/media backup scripts.

For passkeys on `darith.app`, set `DARITH_WEBAUTHN_RP_ID=darith.app` and `DARITH_WEBAUTHN_ORIGIN=https://darith.app`. WebAuthn works on HTTPS and on browser-trusted localhost development addresses.

Database encryption at rest must be enabled with your PostgreSQL host or encrypted server volume. This protects stolen disks and backups, but it is not per-user end-to-end encryption.

Django Admin exposes user identity, password management, subscription plans, subscription access, and feedback intentionally submitted by users. Bank accounts, balances, categories, income, expenses, transfers, goals, user settings, PIN hashes, and passkeys are not registered there. The server and database operator can still access stored rows directly, so this is administrative access control rather than end-to-end encryption.

## Free local use and hosted access

Individuals can run Darith on their own computer for free for personal, noncommercial use. See [DEPLOYMENT.md](DEPLOYMENT.md) for the short local setup.

Hosted access at [darith.app](https://darith.app) is available for people who want to reach the app online at any time. The small monthly contribution helps pay for hosting, backups, maintenance, and updates. [Buy Me a Coffee](https://buymeacoffee.com/darith) supports one-time help and automatically recurring monthly contributions; Darith access is still verified manually after payment is reported.

People using the GitHub repository can also use [Buy Me a Coffee](https://buymeacoffee.com/darith) to support continued development.

## Telegram admin notifications

Darith can notify the administrator when a user registers, submits feedback, or reports a subscription payment. Create a Telegram bot, start a chat with it, and add these values to the server environment:

~~~bash
DARITH_TELEGRAM_BOT_TOKEN=123456:replace-with-your-bot-token
DARITH_TELEGRAM_CHAT_ID=replace-with-your-chat-id
~~~

Restart the Darith application after changing the environment, then verify delivery from the same configured server environment:

~~~bash
python manage.py send_test_telegram
~~~

Both values are required; when either is missing, Telegram notifications remain disabled. Keep the bot token in `/etc/darith.env` or another protected server secret store and never commit it to Git.

Alerts include only the username and the minimum event details. Feedback text and personal financial data are not sent to Telegram. Telegram errors are logged and do not prevent registration, feedback, or payment reporting.


## Licensing

Darith is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE).

The code in this repository may be used for noncommercial purposes as permitted by the license. Commercial use requires separate permission from the copyright holder.

For licensing information, visit [darith.app](https://darith.app).

See [LICENSE](LICENSE) for the full license terms and [CONTRIBUTING.md](CONTRIBUTING.md) before contributing.

## Tests

~~~bash
python manage.py test
python manage.py check
~~~

Optional browser test:

~~~bash
python -m pip install -r requirements-dev.txt
python scripts/ui_smoke.py
~~~

With the local server running, the passkey smoke test creates and removes its own temporary user while checking enrollment, unlock, and passwordless sign-in:

~~~bash
python scripts/passkey_smoke.py
~~~
