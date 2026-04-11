#!/bin/sh
set -eu

TARGET_UID="${APP_UID:-}"
TARGET_GID="${APP_GID:-}"

CURRENT_UID="$(id -u crunchy)"
CURRENT_GID="$(id -g crunchy)"

if [ "$(id -u)" = "0" ]; then
    if [ -n "$TARGET_GID" ] && [ "$TARGET_GID" != "$CURRENT_GID" ]; then
        groupmod -o -g "$TARGET_GID" crunchy
        CURRENT_GID="$TARGET_GID"
    fi

    if [ -n "$TARGET_UID" ] && [ "$TARGET_UID" != "$CURRENT_UID" ]; then
        usermod -o -u "$TARGET_UID" -g "$CURRENT_GID" crunchy
        CURRENT_UID="$TARGET_UID"
    fi

    chown -R "$CURRENT_UID:$CURRENT_GID" /home/crunchy /data /app
    exec gosu crunchy "$@"
fi

exec "$@"
