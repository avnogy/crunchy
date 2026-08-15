#!/bin/sh
set -eu

APP_USER="crunchy"
APP_HOME="/home/${APP_USER}"
APP_DIR="/app"
CONFIG_DIR="/config"
DATA_DIR="/data"

target_uid="${APP_UID:-}"
target_gid="${APP_GID:-}"
service_mode="${CRUNCHY_SERVICE_MODE:-web}"

current_uid="$(id -u "${APP_USER}")"
current_gid="$(id -g "${APP_USER}")"

remap_user() {
    if [ -n "${target_gid}" ] && [ "${target_gid}" != "${current_gid}" ]; then
        groupmod -o -g "${target_gid}" "${APP_USER}"
        current_gid="${target_gid}"
    fi

    if [ -n "${target_uid}" ] && [ "${target_uid}" != "${current_uid}" ]; then
        usermod -o -u "${target_uid}" -g "${current_gid}" "${APP_USER}"
        current_uid="${target_uid}"
    fi
}

fix_permissions() {
    chown -R "${current_uid}:${current_gid}" "${APP_HOME}" "${DATA_DIR}" "${CONFIG_DIR}"
}

if [ "$#" = "0" ]; then
    case "${service_mode}" in
        web)
            set -- uvicorn "app.main:app" --host "${APP_HOST:-0.0.0.0}" --port "${APP_PORT:-8000}"
            ;;
        worker)
            set -- python -m worker.ffmpeg
            ;;
        *)
            echo "Unknown CRUNCHY_SERVICE_MODE: ${service_mode}" >&2
            exit 1
            ;;
    esac
fi

if [ "$(id -u)" = "0" ]; then
    remap_user
    fix_permissions
    exec gosu "${APP_USER}" "$@"
fi

exec "$@"
