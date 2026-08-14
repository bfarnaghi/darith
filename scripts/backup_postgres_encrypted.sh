#!/usr/bin/env bash
# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.

set -Eeuo pipefail
umask 077

for command_name in age date mkdir mktemp mv pg_dump rm tar; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command_name}" >&2
        exit 1
    fi
done

required_variables=(
    DARITH_BACKUP_RECIPIENT
    DJANGO_DB_HOST
    DJANGO_DB_NAME
    DJANGO_DB_PASSWORD
    DJANGO_DB_USER
)
for variable_name in "${required_variables[@]}"; do
    if [[ -z "${!variable_name:-}" ]]; then
        printf 'Required environment variable is missing: %s\n' "${variable_name}" >&2
        exit 1
    fi
done

database_sslmode="${DJANGO_DB_SSLMODE:-require}"
case "${database_sslmode}" in
    require | verify-ca | verify-full) ;;
    *)
        printf 'DJANGO_DB_SSLMODE must require an encrypted connection.\n' >&2
        exit 1
        ;;
esac

backup_directory="${DARITH_BACKUP_DIR:-/var/backups/darith}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
destination="${backup_directory}/darith-${timestamp}.dump.age"
media_directory="${DJANGO_MEDIA_ROOT:-/var/lib/darith/media}"
media_destination="${backup_directory}/darith-${timestamp}-media.tar.age"

mkdir -p -- "${backup_directory}"
temporary_file="$(mktemp "${backup_directory}/.darith-backup-XXXXXX.dump.age")"
temporary_media_file="$(mktemp "${backup_directory}/.darith-media-XXXXXX.tar.age")"
trap 'rm -f -- "${temporary_file}" "${temporary_media_file}"' EXIT

export PGPASSWORD="${DJANGO_DB_PASSWORD}"
export PGSSLMODE="${database_sslmode}"
if [[ -n "${DJANGO_DB_SSLROOTCERT:-}" ]]; then
    export PGSSLROOTCERT="${DJANGO_DB_SSLROOTCERT}"
fi

pg_dump \
    --host="${DJANGO_DB_HOST}" \
    --port="${DJANGO_DB_PORT:-5432}" \
    --username="${DJANGO_DB_USER}" \
    --dbname="${DJANGO_DB_NAME}" \
    --format=custom \
    --no-owner \
    --no-privileges \
    | age --recipient "${DARITH_BACKUP_RECIPIENT}" > "${temporary_file}"

mv -- "${temporary_file}" "${destination}"
printf 'Encrypted backup created: %s\n' "${destination}"

if [[ -d "${media_directory}" ]]; then
    tar --directory="${media_directory}" --create --file=- . \
        | age --recipient "${DARITH_BACKUP_RECIPIENT}" > "${temporary_media_file}"
    mv -- "${temporary_media_file}" "${media_destination}"
    printf 'Encrypted media backup created: %s\n' "${media_destination}"
else
    rm -f -- "${temporary_media_file}"
fi

trap - EXIT
