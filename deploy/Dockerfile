FROM node:22.22.2-alpine AS web
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.14.3-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/srv/backend
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /srv
COPY backend/requirements-lock.txt /tmp/requirements-lock.txt
RUN pip install --no-cache-dir -r /tmp/requirements-lock.txt
RUN useradd --uid 10001 --create-home revero && mkdir /data && chown revero /data
COPY --chown=revero backend/ ./backend/
COPY --from=web --chown=revero /web/dist ./web/
USER 10001:10001
ENV REVERO_DB_PATH=/data/revero.sqlite3 REVERO_REQUIRE_MIGRATED=true REVERO_FRONTEND_DIR=/srv/web
CMD ["python","-m","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--no-access-log"]
