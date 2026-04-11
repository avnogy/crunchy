# crunchy

`crunchy` is a small web app for downloading smaller offline-friendly versions of media from Jellyfin.

## Why

Jellyfin does not have a built-in offline sync flow that fits this use case, and the available third-party clients were not a good fit either. The project is heavily inspired by [squishy](https://github.com/cleverdevil/squishy), but uses Jellyfin itself for transcoding because that keeps the setup simpler and allows Nvidia transcoding support.

## How It Works

`crunchy` connects to Jellyfin, provides a web UI for browsing the library, starts a transcode job through Jellyfin, and exposes the finished file for download.

## Quick Start

```bash
docker compose up --build
```

Set the values you need in `.env` first.

| Variable | Default | Notes |
| --- | --- | --- |
| `JELLYFIN_API_URL` | `""` | Jellyfin base URL. |
| `JELLYFIN_API_KEY` | `""` | Jellyfin API key. |
| `JELLYFIN_USER_ID` | `""` | Jellyfin user ID used for library access and transcoding. |
| `APP_PASSWORD` | `""` | Basic auth password for the fixed `admin` user. If empty on first boot, one is generated and can be found in the log output. |
| `SETTINGS_FILE` | `/config/settings.json` | Runtime settings file path. |
| `TRANSCODING_TEMP_DIR` | `/data/temp` | Temporary transcode output directory. |
| `OUTPUT_DIR` | `/data/output` | Final downloaded files directory. |
| `MAX_CONCURRENT_JOBS` | `1` | Number of transcode jobs processed at once. |
| `JOBS_POLL_INTERVAL_MS` | `3000` | UI job status polling interval. |
| `APP_HOST` | `0.0.0.0` | App bind host. |
| `APP_PORT` | `8000` | App bind port. |
| `LOG_LEVEL` | `INFO` | Application log level. |
| `FFMPEG_FLAGS` | `""` | Extra ffmpeg flags, space-separated. |
| `APP_UID` | `1000` | Docker build arg used for the container user ID. |
| `APP_GID` | `1000` | Docker build arg used for the container group ID. |

The compose setup stores app settings in `./config/settings.json` and writes finished files to `./output`.

## Notes

- Run it behind HTTPS if you expose it outside your local network.

## Presets

There are a few default presets for smaller mobile downloads, and they can be adjusted in the app settings.
