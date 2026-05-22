# crunchy

`crunchy` is a small web app for downloading smaller offline-friendly versions of media from Jellyfin.

## Why

Jellyfin does not have a built-in offline sync flow that fits this use case, and the available third-party clients were not a good fit either. The project is heavily inspired by [squishy](https://github.com/cleverdevil/squishy), but uses Jellyfin itself for transcoding because that keeps the setup simpler and allows Nvidia transcoding support.

## How It Works

`crunchy` connects to Jellyfin, provides a web UI for browsing the library, starts a transcode job through Jellyfin, and exposes the finished file for download.

Workers can be scaled horizontally because they only coordinate through Redis.

## Quick Start

1. You can copy `.env.example` to `.env` and fill it up or just skip it and set everything in the UI.
2. Start the stack with [`./docker/docker-compose.yml`](./docker/docker-compose.yml):

```bash
docker compose -f docker/docker-compose.yml up
```

For local development with a local image build:

```bash
docker compose -f docker/docker-compose.yml -f docker/docker-compose.dev.yml up --build
```

## Configuration

Environment variables are used as the initial settings source. After first boot, the app persists settings to `/config/settings.json`, and changes made in the Settings page become the active configuration for later restarts.

If `APP_PASSWORD` is empty on first boot, `crunchy` generates a password for the fixed Basic Auth user `admin`, logs it once at startup, and saves it in `/config/settings.json`.

| Variable                | Default                         | Notes                                                                                                                              |
| ----------------------- | ------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `JELLYFIN_API_URL`      | `""`                            | Jellyfin base URL.                                                                                                                 |
| `JELLYFIN_API_KEY`      | `""`                            | Jellyfin API key.                                                                                                                  |
| `JELLYFIN_USER_ID`      | `""`                            | Jellyfin user ID used for library access and playback info.                                                                        |
| `APP_PASSWORD`          | `""`                            | Password for the fixed Basic Auth user `admin`.                                                                                    |
| `CONFIG_PATH`           | `./data/config`                 | Host path mounted at `/config`.                                                                                                    |
| `OUTPUT_PATH`           | `./data/output`                 | Host path mounted at `/data/output`.                                                                                               |
| `TEMP_PATH`             | `./data/temp`                   | Host path mounted at `/data/temp`.                                                                                                 |
| `REDIS_HOST`            | `127.0.0.1`                     | Redis host used by the app and worker in the default host-networked compose setup.                                                 |
| `REDIS_PORT`            | `6379`                          | Redis port used by the app and worker.                                                                                             |
| `JOBS_POLL_INTERVAL_MS` | `3000`                          | UI polling interval for the Jobs page. Minimum `500`.                                                                              |
| `APP_HOST`              | `0.0.0.0`                       | App bind host.                                                                                                                     |
| `APP_PORT`              | `8000`                          | App bind port.                                                                                                                     |
| `LOG_LEVEL`             | `INFO`                          | One of the app's supported log levels.                                                                                             |
| `FFMPEG_FLAGS`          | `""`                            | Extra ffmpeg flags. The app parses this like a shell command line and rejects reserved flags that would override required options. |
| `APP_UID`               | `1000`                          | Optional runtime UID override for the container user.                                                                              |
| `APP_GID`               | `1000`                          | Optional runtime GID override for the container group.                                                                             |
| `CRUNCHY_IMAGE`         | `ghcr.io/avnogy/crunchy:latest` | Image used by [`./docker/docker-compose.yml`](./docker/docker-compose.yml).                                                        |

## Paths

The app and workers always use fixed in-container paths:

- `/config/settings.json`
- `/data/temp`
- `/data/output`

`CONFIG_PATH`, `TEMP_PATH`, and `OUTPUT_PATH` only change the host-side bind mounts. After changing any of them, restart the containers so Docker recreates the mounts.

Both the web app and the worker mount the same config, temp, and output directories so job logs and completed files are immediately visible to the API.

## Presets

The Settings page manages named transcode presets. Jobs reference those presets by key.

Each preset can define:

- `name`
- `maxHeight`
- `videoBitrate`
- `audioBitrate`
- `videoCodec`
- `audioCodec`
- `segmentContainer`

The built-in defaults target smaller downloads and currently use `h265`, `aac`, and `mp4`.

## Operations

- Health check: `GET /healthz`
- Authentication: HTTP Basic Auth with the fixed username `admin`
- Worker scaling: scale `ffmpeg-worker` if you want to process more queued jobs in parallel
- Downloads and temp files can be cleared from the Settings page
- Jobs can be cancelled from the Jobs page

## Notes

- Run it behind HTTPS if you expose it outside your local network.
- Runtime writes are expected under `/config`, `/data/output`, and `/data/temp`; the bundled application code under `/app` is read-only in the container image.
