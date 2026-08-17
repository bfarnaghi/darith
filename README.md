<p align="center">
  <img src="web/static/images/logo.png" alt="Darith logo" width="180">
</p>

# Darith

Darith is a responsive personal-finance app that tracks accounts, recurring plans, and savings goals while showing what is safe to spend on mobile or desktop.

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

1. Add each real bank account and its current balance under **Accounts**. Turn off **Include in monthly budget** for cash or other accounts that you only want to track separately.
2. Set **Expected daily costs** from the Overview. Darith reserves that amount for every remaining day of the month.
3. Record manual income and expenses. Their selected bank balance updates immediately.
4. Use **Transfer** to move money between banks, from a bank to a goal, or from a goal back to a bank.
5. Add salary, rent, bills, and subscriptions under **Monthly plans**. The first payment or charge date sets the monthly day; the optional stop date does not create another transaction.
6. Create an ongoing savings goal with a monthly amount, or enter a target amount and target date. Choose the bank that will fund it.
7. When a monthly savings reminder appears, press **Mark saved**. Darith transfers the calculated amount from the selected bank into that goal once for the month.
8. Check **Free to spend** for money available now after uncovered bills, expected daily costs, and unfunded savings goals. Future surplus appears in the month-end outlook instead of becoming spendable early.
9. Use **Export CSV** above the transaction list to download your accounts, goals, plans, transactions, and transfers.
10. Use **Settings → Appearance** to choose a theme, display currency, profile picture, and budget-state GIFs. Iranian Toman is shown as `IRT`. Currency changes labels only and does not convert stored amounts.
11. Press the eye button in **Free to spend** to hide or show dashboard amounts. Darith remembers this choice for your user account.
12. In Settings, you can upload and remove a GIF for each budget state. Profile pictures and GIFs are limited to 2 MB and 1200 x 1200 pixels; GIFs are also limited to 300 frames.
13. Under **Settings → Security**, add a passkey or Darith PIN and choose an inactivity timeout. Passkeys use the security built into your phone or computer; Darith does not receive your fingerprint or face data.
14. Use **Feedback** in the account menu to send a comment to the Darith administrator.
15. Use **Settings → Account** to permanently delete your user account and live data. Darith requires your current password, an acknowledgement, an exact typed signature, and a final confirmation.

Editing a transaction always updates its account balance. Deleting a transaction or transfer reverses its previous balance change by default; choose **Leave balances unchanged** under **Settings → Behavior** when you prefer to correct balances manually. A bank or goal with transfer history is kept to protect the ledger.

Due recurring items are processed whenever the dashboard opens. A server can also run them daily without a login:

~~~bash
python manage.py process_scheduled_transactions
~~~

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


## License

Darith is publicly available as **source-available software** under the [PolyForm Noncommercial License 1.0.0](LICENSE). Academic research, education, evaluation, and other permitted noncommercial uses are welcome. Commercial use by anyone other than the copyright holder requires a separate written license; contact `b.farnaghi@gmail.com`.

See [NOTICE](NOTICE) for attribution and [CONTRIBUTING.md](CONTRIBUTING.md) before contributing. PolyForm Noncommercial is not an OSI-approved open-source license.

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
