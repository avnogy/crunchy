# crunchy
[![Build and Push to GHCR](https://github.com/avnogy/crunchy/actions/workflows/build-push-ghcr.yml/badge.svg?branch=main&event=release)](https://github.com/avnogy/crunchy/actions/workflows/build-push-ghcr.yml)

`crunchy` is a small web app for downloading smaller offline-friendly versions of media from Jellyfin.

## Why

Jellyfin does not have a built-in offline sync flow that fits this use case, and the available third-party clients were not a good fit either. The project is heavily inspired by [squishy](https://github.com/cleverdevil/squishy), but uses Jellyfin itself for transcoding because that keeps the setup simpler and allows Nvidia transcoding support.

## How It Works

`crunchy` connects to Jellyfin, provides a web UI for browsing the library, starts a transcode job through Jellyfin, and exposes the finished file for download.

## Quick Start

```bash
docker compose up
```

Set the values you need in `.env` first.

`docker-compose.yml` now uses a **shared RAM-backed tmpfs volume** (`shared_temp`) for the internal path `/data/temp`. Both the web app and the ffmpeg worker mount this same temporary filesystem, so files such as job logs are immediately visible to the API.

For local development with a local image build, use:

```bash
docker compose -f docker-compose.dev.yml up --build
```

| Variable | Default | Notes |
| --- | --- | --- |
| `JELLYFIN_API_URL` | `""` | Jellyfin base URL. |
| `JELLYFIN_API_KEY` | `""` | Jellyfin API key. |
| `JELLYFIN_USER_ID` | `""` | Jellyfin user ID used for library access and transcoding. |
| `APP_PASSWORD` | `""` | Basic auth password for the fixed `admin` user. If empty on first boot, one is generated and can be found in the log output. |
| `SETTINGS_FILE` | `/config/settings.json` | Runtime settings file path. |
| `OUTPUT_PATH` | `./output` | Host-side path mounted to the fixed in-container output directory `/data/output`. |
| `JOBS_POLL_INTERVAL_MS` | `3000` | UI job status polling interval. |
| `APP_HOST` | `0.0.0.0` | App bind host. |
| `APP_PORT` | `8000` | App bind port. |
| `LOG_LEVEL` | `INFO` | Application log level. |
| `FFMPEG_FLAGS` | `""` | Extra ffmpeg flags, space-separated. |
| `APP_UID` | `1000` | Optional runtime UID override for the container user. |
| `APP_GID` | `1000` | Optional runtime GID override for the container group. |
| `CRUNCHY_IMAGE` | `ghcr.io/avnogy/crunchy:latest` | Image used by the compose files. |

## Shared Temp Storage

The app and the worker always use the fixed internal paths `/data/temp` and `/data/output`.

- By default a **RAM-backed `tmpfs` volume** named `shared_temp` is mounted at `/data/temp`. This volume is shared between the `crunchy` and `ffmpeg-worker` services, allowing temporary files (e.g., ffmpeg logs) to be accessed by both containers.
- `OUTPUT_PATH` controls the host path for completed downloads at `/data/output` and remains unchanged.

Use RAM-backed temp storage when you want faster temporary I/O and want the temporary files to disappear on container restart.

If you prefer the temporary files to be stored on disk instead, replace the `shared_temp:/data/temp` mount in both services with a bind mount, for example:

```yaml

volumes:
  - ${OUTPUT_PATH:-./output}:/data/output
  - ./config:/config
  - ./temp:/data/temp
```

The ffmpeg worker lives under [`worker/`](./worker) as a separate service that only communicates through Redis. To process more jobs in parallel, scale the `ffmpeg-worker` service.

## Container Releases

GitHub Actions can publish an image to `ghcr.io` from `main` and from version tags like `v1.0.0`.

The existing `APP_UID` and `APP_GID` behavior is preserved for both local builds and published images:

- Production `docker compose up` uses `ghcr.io/avnogy/crunchy:latest` by default and can be overridden with `CRUNCHY_IMAGE`.
- Local `docker compose -f docker-compose.dev.yml up --build` still works with a local build.
- Published images can remap the `crunchy` user at container startup by setting `APP_UID` and `APP_GID` as environment variables.

## Notes

- Run it behind HTTPS if you expose it outside your local network.

## Presets

There are a few default presets for smaller mobile downloads, and they can be adjusted in the app settings. Each preset can define `maxHeight`, `videoBitrate`, `audioBitrate`, `videoCodec`, `audioCodec`, and `segmentContainer`; the defaults use `h265`, `aac`, and `mp4`.
