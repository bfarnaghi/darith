# Deployment Guide

This guide keeps local development simple and gives a secure baseline for a public Darith server.

## Protection included

- Production refuses the development secret, wildcard hosts, SQLite, and unencrypted PostgreSQL network connections.
- Browser logins use HTTPS-only cookies, HSTS, CSRF protection, and Argon2 password hashing.
- PostgreSQL traffic uses TLS. Database disks and automatic snapshots must also be encrypted by your database provider.
- The included backup script encrypts database and private GIF backups with `age` before they reach disk.

This is server-side protection, not per-user end-to-end encryption. Darith separates users in application queries, but a database administrator can still read financial rows. True per-user encryption would require a separate key-management design and would prevent several database calculations.

## Local server

SQLite remains the default when `DJANGO_DEBUG=true`:

~~~bash
git clone YOUR_REPOSITORY_URL darith
cd darith
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
~~~

Open `http://127.0.0.1:8000`. To test from another device on your private network:

~~~bash
DJANGO_ALLOWED_HOSTS="localhost,127.0.0.1,YOUR_SERVER_IP" \
python manage.py runserver 0.0.0.0:8000
~~~

Do not expose Django's development server to the internet.

## Public server

The example below uses Ubuntu, Gunicorn, Nginx, and a managed PostgreSQL 14+ database.

### 1. Prepare the server

~~~bash
sudo apt update
sudo apt install age nginx postgresql-client python3-venv
sudo useradd --system --create-home --home-dir /var/www/darith --shell /usr/sbin/nologin darith
sudo -u darith git clone YOUR_REPOSITORY_URL /var/www/darith/app
sudo -u darith python3 -m venv /var/www/darith/app/.venv
sudo -u darith /var/www/darith/app/.venv/bin/python -m pip install -r /var/www/darith/app/requirements.txt
sudo install -d -o darith -g darith -m 0700 /var/lib/darith/media
~~~

In your PostgreSQL provider:

1. Create a database and a dedicated Darith user.
2. Enable encryption at rest and automatic backups or point-in-time recovery.
3. Require TLS and download the provider's CA certificate when one is offered.
4. Restrict network access to your web server where the provider supports it.

### 2. Configure secrets

Generate separate application and database passwords:

~~~bash
python3 -c "import secrets; print(secrets.token_urlsafe(64))"
~~~

Install the environment template and edit every placeholder:

~~~bash
sudo install -o root -g darith -m 0640 /var/www/darith/app/.env.example /etc/darith.env
sudoedit /etc/darith.env
~~~

Use your real domain in `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS`. Use `DJANGO_DB_SSLMODE=verify-full` with the provider CA when possible. If your provider only supports encrypted TLS without a supplied CA, use `require`.

Install a provider CA like this and set its path in `/etc/darith.env`:

~~~bash
sudo install -o root -g darith -m 0640 provider-ca.pem /etc/darith-postgres-ca.pem
~~~

### 3. Validate and initialize

Run Django with the production environment:

~~~bash
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py check --deploy'
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py migrate'
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py collectstatic --noinput'
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py createsuperuser'
~~~

Do not continue until `check --deploy` reports no warnings.

### 4. Run Gunicorn

Create `/etc/systemd/system/darith.service`:

~~~ini
[Unit]
Description=Darith web application
Wants=network-online.target
After=network-online.target

[Service]
User=darith
Group=darith
WorkingDirectory=/var/www/darith/app
EnvironmentFile=/etc/darith.env
ExecStart=/var/www/darith/app/.venv/bin/gunicorn darith.wsgi:application --workers 2 --bind 127.0.0.1:8001 --access-logfile - --error-logfile - --no-control-socket
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectControlGroups=true
ProtectHome=true
ProtectKernelModules=true
ProtectKernelTunables=true
ProtectSystem=strict
RestrictSUIDSGID=true
ReadWritePaths=/var/lib/darith/media

[Install]
WantedBy=multi-user.target
~~~

The control socket is disabled because Darith does not use Gunicorn's optional
runtime control interface, and the hardened service intentionally keeps the
application directory read-only.

Start it:

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now darith
sudo systemctl status darith
~~~

### 5. Process recurring items

Create `/etc/systemd/system/darith-scheduled.service`:

~~~ini
[Unit]
Description=Process Darith scheduled transactions
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=darith
Group=darith
WorkingDirectory=/var/www/darith/app
EnvironmentFile=/etc/darith.env
ExecStart=/var/www/darith/app/.venv/bin/python manage.py process_scheduled_transactions
UMask=0077
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
~~~

Create `/etc/systemd/system/darith-scheduled.timer`:

~~~ini
[Unit]
Description=Run Darith scheduled transactions daily

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=10m

[Install]
WantedBy=timers.target
~~~

Enable it:

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now darith-scheduled.timer
~~~

The command can run more than once; Darith posts each monthly occurrence only once.

### 6. Add HTTPS and Nginx

Obtain a TLS certificate from your hosting provider or Let's Encrypt. Then create `/etc/nginx/sites-available/darith` and replace the example domain:

~~~nginx
server {
    listen 80;
    listen [::]:80;
    server_name darith.app www.darith.app;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name darith.app www.darith.app;

    ssl_certificate /etc/letsencrypt/live/darith.app/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/darith.app/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;

    client_max_body_size 7m;
    add_header Content-Security-Policy "default-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; upgrade-insecure-requests" always;
    add_header Permissions-Policy "camera=(), geolocation=(), microphone=()" always;

    location /static/ {
        alias /var/www/darith/app/staticfiles/;
        access_log off;
        expires 7d;
    }

    location / {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_pass http://127.0.0.1:8001;
    }
}
~~~

Enable and reload Nginx:

~~~bash
sudo ln -s /etc/nginx/sites-available/darith /etc/nginx/sites-enabled/darith
sudo nginx -t
sudo systemctl reload nginx
~~~

Allow only SSH and web traffic through the firewall:

~~~bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
~~~

### 7. Optional manual subscriptions

Darith works without subscriptions while `DARITH_SUBSCRIPTIONS_ENABLED=false`. To enable manual payments:

1. In `/admin/`, create one active **Subscription plan**.
2. Set the monthly EUR price, optional trial length, and clear, specific payment instructions. The instructions may contain bank-transfer, PayPal, Revolut, Wise, or other details.
3. Set `DARITH_SUBSCRIPTIONS_ENABLED=true` in `/etc/darith.env`, run `manage.py check --deploy`, and restart Darith.
4. Create a normal test account and confirm that it sees the trial or manual payment page.
5. Pay externally using the displayed `DARITH-......` user reference, then press **I have paid**.
6. In `/admin/`, open **User subscriptions** and filter for **Payment reported**.
7. Verify the external payment, change the status to **Active**, set **Access until** to the paid-through date, and optionally record the payment method or reference in **Payment note**.

The admin list also includes an **Activate or extend selected users by 30 days** action. To grant complimentary access, activate the user through a chosen date and explain it in the payment note. The **Expire selected users now** action revokes access immediately.

Darith does not process money, save payment credentials, or automatically renew access. You must verify every payment and extend the date manually. Once the access date passes, the middleware blocks the dashboard until access is extended.

Before accepting payments, publish terms, a privacy notice, cancellation and refund rules, business contact details, and the tax/VAT information required where you operate. Confirm these obligations with qualified legal and tax professionals.

### 8. Configure encrypted backups

Create an `age` key on a trusted computer, not on the web server:

~~~bash
age-keygen -o darith-backup.key
chmod 600 darith-backup.key
age-keygen -y darith-backup.key
~~~

Keep `darith-backup.key` offline and in a second secure location. Put only the printed public recipient in `DARITH_BACKUP_RECIPIENT` inside `/etc/darith.env`.

Prepare the server backup directory:

~~~bash
sudo install -d -o darith -g darith -m 0700 /var/backups/darith
~~~

The backup script also encrypts `/var/lib/darith/media`, which contains private dashboard GIFs. Create `/etc/systemd/system/darith-backup.service`:

~~~ini
[Unit]
Description=Create encrypted Darith database and media backups
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=darith
Group=darith
WorkingDirectory=/var/www/darith/app
EnvironmentFile=/etc/darith.env
ExecStart=/var/www/darith/app/scripts/backup_postgres_encrypted.sh
UMask=0077
NoNewPrivileges=true
PrivateDevices=true
PrivateTmp=true
ProtectHome=true
ProtectSystem=strict
ReadWritePaths=/var/backups/darith
~~~

Create `/etc/systemd/system/darith-backup.timer`:

~~~ini
[Unit]
Description=Back up Darith every day

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30m

[Install]
WantedBy=timers.target
~~~

Enable the timer and test one backup:

~~~bash
sudo systemctl daemon-reload
sudo systemctl enable --now darith-backup.timer
sudo systemctl start darith-backup.service
sudo systemctl status darith-backup.service
sudo -u darith ls -lh /var/backups/darith
~~~

Copy both encrypted database and media backups to storage outside this server and set a retention policy there. Periodically test a database restore into a separate empty database from a trusted computer that has the private key and a protected restore environment file:

~~~bash
set -a
source /secure/path/darith-restore.env
set +a
export DJANGO_DB_NAME=darith_restore_test
export DARITH_BACKUP_IDENTITY=/secure/path/darith-backup.key
scripts/restore_postgres_encrypted.sh --confirm-overwrite BACKUP.dump.age
~~~

The restore command intentionally requires `--confirm-overwrite` because it replaces the configured database contents.

To test a private-media restore, stop Darith and decrypt a media backup into an empty protected directory:

~~~bash
sudo systemctl stop darith
sudo install -d -o darith -g darith -m 0700 /var/lib/darith/media-restore-test
age --decrypt --identity /secure/path/darith-backup.key BACKUP-media.tar.age \
    | sudo -u darith tar -xf - -C /var/lib/darith/media-restore-test
sudo systemctl start darith
~~~

Inspect the restored directory before replacing production media. Never expose `DJANGO_MEDIA_ROOT` with an Nginx `alias`; Darith serves each GIF through an authenticated owner-only view.

## Updating Darith

Back up first, then update:

~~~bash
sudo systemctl start darith-backup.service
sudo -u darith git -C /var/www/darith/app pull --ff-only
sudo -u darith /var/www/darith/app/.venv/bin/python -m pip install -r /var/www/darith/app/requirements.txt
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py check --deploy'
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py migrate'
sudo -u darith bash -c 'set -a; source /etc/darith.env; set +a; cd /var/www/darith/app; .venv/bin/python manage.py collectstatic --clear --noinput'
sudo systemctl restart darith
~~~

Darith fingerprints production CSS, JavaScript, and image filenames. Always run
`collectstatic` before restarting the application so browsers and CDNs receive a
new asset URL whenever its contents change.

Check logs after each update:

~~~bash
sudo journalctl -u darith -n 100 --no-pager
sudo systemctl list-timers 'darith-*'
~~~
