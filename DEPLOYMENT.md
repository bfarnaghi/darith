# Deployment Guide

This guide covers a local network server and a small Ubuntu website using Gunicorn and Nginx.

## Local server

Install and prepare the app:

```bash
git clone YOUR_REPOSITORY_URL Darith
cd Darith
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
```

Start it for devices on your local network:

```bash
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,YOUR_SERVER_IP" \
python manage.py runserver 0.0.0.0:8000
```

Open `http://YOUR_SERVER_IP:8000` from your phone or computer. This server is for private testing, not a public website.

## Public website

1. Point your domain to the server.
2. Clone the project and run the installation commands above.
3. Create a secret key:

```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

4. Create `/etc/darith.env`:

```text
DJANGO_SECRET_KEY=PASTE_YOUR_SECRET_KEY
DJANGO_DEBUG=false
DJANGO_ALLOWED_HOSTS=money.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://money.example.com
DJANGO_TIME_ZONE=Europe/Rome
```

Protect that file:

```bash
sudo chmod 600 /etc/darith.env
```

5. Collect static files:

```bash
set -a
source /etc/darith.env
set +a
.venv/bin/python manage.py collectstatic --noinput
```

6. Create `/etc/systemd/system/darith.service`:

```ini
[Unit]
Description=Darith
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/var/www/Darith
EnvironmentFile=/etc/darith.env
ExecStart=/var/www/Darith/.venv/bin/gunicorn darith.wsgi:application --workers 2 --bind 127.0.0.1:8001
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Adjust `WorkingDirectory` and `ExecStart` if you cloned the app elsewhere. Make sure `www-data` can write `db.sqlite3` and its containing directory.

Start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now darith
```

7. Create `/etc/nginx/sites-available/darith`:

```nginx
server {
    listen 80;
    server_name money.example.com;

    location /static/ {
        alias /var/www/Darith/staticfiles/;
    }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_pass http://127.0.0.1:8001;
    }
}
```

Enable the site, test Nginx, and reload it:

```bash
sudo ln -s /etc/nginx/sites-available/darith /etc/nginx/sites-enabled/darith
sudo nginx -t
sudo systemctl reload nginx
```

8. Add HTTPS with your hosting provider or Certbot before signing in or entering financial data.

After each app update:

```bash
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart darith
```

Back up `db.sqlite3` regularly. For many users or multiple app servers, move the database to PostgreSQL first.
