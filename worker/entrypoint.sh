#!/bin/sh
set -eu

exec python -m app.ffmpeg_worker
