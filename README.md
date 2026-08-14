<p align="center">
  <img src="web/static/images/logo.png" alt="Darith logo" width="180">
</p>

# Darith

Darith is a responsive Django app for managing personal money on mobile and desktop.

**Website:** [https://darith.app](https://darith.app)

## What it does

- Tracks current balances across multiple bank accounts.
- Adds, edits, and removes income, expenses, and transfers.
- Moves money between bank accounts and savings goals.
- Posts recurring income and expenses from their effective dates.
- Supports ongoing monthly savings and dated targets such as a bicycle or holiday.
- Keeps a separate balance for every savings goal.
- Calculates monthly goal contributions and shows a reminder until you mark them saved.
- Reserves expected daily costs, upcoming bills, and goal funding before calculating free spending.
- Warns when spendable accounts cannot cover the remaining daily costs.
- Lets each user choose a display currency and dashboard color theme.
- Shows an optional private GIF chosen by the user for on-track, warning, and out-of-budget states.
- Exports the signed-in user's financial data as a CSV file.
- Optionally supports free trials and administrator-verified manual subscriptions.

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

1. Add each real bank account and its current balance under **Accounts**.
2. Set **Expected daily costs** from the Overview. Darith reserves that amount for every remaining day of the month.
3. Record manual income and expenses. Their selected bank balance updates immediately.
4. Use **Transfer** to move money between banks, from a bank to a goal, or from a goal back to a bank.
5. Add salary, rent, bills, and subscriptions under **Monthly plans**. The first payment or charge date sets the monthly day; the optional stop date does not create another transaction.
6. Create an ongoing savings goal with a monthly amount, or enter a target amount and target date. Choose the bank that will fund it.
7. When a monthly savings reminder appears, press **Mark saved**. Darith transfers the calculated amount from the selected bank into that goal once for the month.
8. Check **Free to spend** for money available now after uncovered bills, expected daily costs, and unfunded savings goals. Future surplus appears in the month-end outlook instead of becoming spendable early.
9. Use **Export CSV** above the transaction list to download your accounts, goals, plans, transactions, and transfers.
10. Use the gear button in **Free to spend** to choose your display currency and color theme, or upload and remove a GIF for each budget state. Currency changes labels only and does not convert stored amounts. GIFs are limited to 2 MB, 1200 x 1200 pixels, and 300 frames.

Editing or deleting a transaction or transfer reverses its previous balance change. A bank or goal with transfer history is kept to protect the ledger.

Due recurring items are processed whenever the dashboard opens. A server can also run them daily without a login:

~~~bash
python manage.py process_scheduled_transactions
~~~

## Public deployment

Production mode requires PostgreSQL with TLS and refuses insecure defaults. Darith also uses Argon2 password hashing, secure cookies, HTTPS redirects, browser security headers, private authenticated GIF delivery, and encrypted database/media backup scripts.

Database encryption at rest must be enabled with your PostgreSQL host or encrypted server volume. This protects stolen disks and backups, but it is not per-user end-to-end encryption. See [DEPLOYMENT.md](DEPLOYMENT.md) for the complete setup.

## Optional subscriptions

Subscriptions are off by default. When enabled, Darith uses a manual workflow: the administrator sets the monthly price, free-trial length, and payment instructions; users pay externally and report the payment; then the administrator verifies it and sets access through a chosen date in Django Admin.

Darith does not collect card or bank credentials and has no payment-provider dependency. Renewals are also manual. See **Optional manual subscriptions** in [DEPLOYMENT.md](DEPLOYMENT.md).


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
