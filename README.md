<p align="center">
  <img src="web/static/images/logo.png" alt="Darith logo" width="180">
</p>

# Darith

Darith is a personal-finance app that answers one simple question: **how much extra can I safely spend?**

It combines current balances, planned income and expenses, daily spending, savings, and an optional emergency buffer into a clear day-by-day plan.

**Website:** [https://darith.app](https://darith.app)

## Core features

- Safe to spend today
- Day-by-day money timeline
- Once, daily, weekly, and monthly income/expense plans
- Passive confirmation when planned money is actually paid or received
- Flexible savings goals and one-month changes
- Temporary daily-spending adjustments with **Can I spend more?**
- Multiple accounts, transfers, CSV export, themes, currencies, and languages
- Passkeys, Darith PIN, inactivity lock, and secure production settings

## Hosted Premium

The public repository is Darith's core source-available edition. The hosted service at [darith.app](https://darith.app) can also provide Premium features.

### Private Numbers

**Private Numbers** is an optional Premium privacy feature and is **off by default**. It uses a separate privacy password to encrypt financial numbers such as balances, income, expenses, transfers, savings, and planning amounts in the Darith database.

Names, dates, username, and email remain available so the account and planning system can work. If the privacy password is lost after Private Numbers is locked, there is no password reset for the encrypted financial values.

Private Numbers protects stored financial values, but it is not end-to-end encryption: while the feature is unlocked, the Darith server decrypts the numbers in memory so calculations can run.

Additional Premium features may be added to the hosted app over time.

## Run locally

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Open `http://127.0.0.1:8000`, create an account, and sign in.

For deployment notes, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Security

Production mode requires PostgreSQL with TLS and secure Django settings. Darith supports Argon2 password/PIN hashing, WebAuthn passkeys, inactivity locking, secure cookies, HTTPS redirects, browser security headers, and protected user-uploaded images.

The public edition does not claim end-to-end encryption. Database and backup encryption should also be configured at the hosting/storage level.

## Licensing

Darith is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE). Noncommercial use is allowed under the license; commercial use requires separate permission from the copyright holder.

For licensing information, visit [darith.app](https://darith.app).

## Tests

```bash
python manage.py check
python manage.py test
```
