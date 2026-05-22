FROM python:3.12-slim

ARG APP_UID=1000
ARG APP_GID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg gosu \
    && groupadd --gid "${APP_GID}" crunchy \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/crunchy crunchy \
    && mkdir -p /data/temp /data/output \
    && chown -R crunchy:crunchy /app /data /home/crunchy \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY worker ./worker
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
    && chown -R crunchy:crunchy /app \
    && find /app -type d -exec chmod 755 {} + \
    && find /app -type f -exec chmod 444 {} +

EXPOSE 8000

ENTRYPOINT ["docker-entrypoint.sh"]
