# Local Setup

This guide runs Darith privately on your own computer. It is not a public-server deployment guide.

## Requirements

- Python 3.12 or newer
- Git

On Ubuntu or Debian, install the required system packages:

~~~bash
sudo apt update
sudo apt install git python3 python3-venv python3-pip
~~~

## Install Darith

~~~bash
git clone https://github.com/bfarnaghi/darith.git
cd darith
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
~~~

Open [http://127.0.0.1:8000](http://127.0.0.1:8000), create an account, and start using Darith.

Passkeys can work on `127.0.0.1` or `localhost` because browsers treat local development addresses as trusted. Fingerprint and Face ID availability depends on your browser and device.

Keep the terminal open while Darith is running. Stop it with `Ctrl+C`. Start it again later with:

~~~bash
cd darith
source .venv/bin/activate
python manage.py runserver
~~~

## Update

~~~bash
cd darith
git pull
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
~~~

## Back Up Your Data

Copy these items to a safe location while Darith is stopped:

- `db.sqlite3`, which contains your financial records
- `media/`, which contains profile pictures and dashboard GIFs

The Django development server is intended only for your own computer. Do not expose it directly to the public internet.
