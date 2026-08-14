#!/usr/bin/env bash
# Author: Behnam <b.farnaghi@gmail.com>
# AI-assisted implementation; manually reviewed and verified by the developer.

set -Eeuo pipefail
umask 077

if [[ "${1:-}" != "--confirm-overwrite" || -z "${2:-}" ]]; then
    printf 'Usage: %s --confirm-overwrite BACKUP.dump.age\n' "$0" >&2
    printf 'This replaces the contents of the configured PostgreSQL database.\n' >&2
    exit 2
fi

backup_file="$2"
if [[ ! -f "${backup_file}" ]]; then
    printf 'Backup file not found: %s\n' "${backup_file}" >&2
    exit 1
fi

for command_name in age pg_restore; do
    if ! command -v "${command_name}" >/dev/null 2>&1; then
        printf 'Required command not found: %s\n' "${command_name}" >&2
        exit 1
    fi
done

required_variables=(
    DARITH_BACKUP_IDENTITY
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

export PGPASSWORD="${DJANGO_DB_PASSWORD}"
export PGSSLMODE="${database_sslmode}"
if [[ -n "${DJANGO_DB_SSLROOTCERT:-}" ]]; then
    export PGSSLROOTCERT="${DJANGO_DB_SSLROOTCERT}"
fi

age --decrypt --identity "${DARITH_BACKUP_IDENTITY}" "${backup_file}" \
    | pg_restore \
        --host="${DJANGO_DB_HOST}" \
        --port="${DJANGO_DB_PORT:-5432}" \
        --username="${DJANGO_DB_USER}" \
        --dbname="${DJANGO_DB_NAME}" \
        --clean \
        --if-exists \
        --no-owner \
        --no-privileges \
        --single-transaction \
        --exit-on-error

printf 'Database restored from: %s\n' "${backup_file}"
