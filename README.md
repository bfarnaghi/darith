# Darith

Darith is a responsive Django app for managing personal money in EUR.

## What it does

- Tracks the current balance of multiple bank accounts.
- Adds, edits, and removes manual income and expenses.
- Organizes expenses and income with personal categories.
- Posts monthly income and expenses automatically on their due date.
- Reserves monthly savings goals.
- Shows how much is free to spend for the rest of the month and per day.
- Warns when the projected balance cannot cover planned expenses and savings.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000`, create an account, and sign in.

## How to use it

1. Add each bank account with its current real balance.
2. Record manual income or expenses. The selected account balance updates automatically.
3. Add salary, rent, bills, and similar items under **Monthly plans**. Due items are posted when you open the dashboard.
4. Add a monthly savings goal. It is reserved in the budget but is not moved between accounts.
5. Check **Free to spend** for the amount left after upcoming monthly income, expenses, and savings.

Editing or deleting a transaction reverses its old balance change. Deleting a bank account keeps its transaction history.

For server setup, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Tests

```bash
python manage.py test
```

Optional browser test:

```bash
pip install -r requirements-dev.txt
python scripts/ui_smoke.py
```
