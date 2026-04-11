FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

ARG APP_UID=1000
ARG APP_GID=1000

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && groupadd --gid "${APP_GID}" crunchy \
    && useradd --uid "${APP_UID}" --gid "${APP_GID}" --create-home --home-dir /home/crunchy crunchy \
    && mkdir -p /data/temp /data/output \
    && chown -R crunchy:crunchy /app /data /home/crunchy \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
RUN chown -R crunchy:crunchy /app

EXPOSE 8000

USER crunchy

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
