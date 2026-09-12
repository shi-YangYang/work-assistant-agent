FROM python:3.12.14-slim-bookworm AS service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src/python
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements-server.lock ./
RUN pip install --no-cache-dir -r requirements-server.lock
COPY src/python/paa_server ./src/python/paa_server
RUN useradd --uid 10001 --create-home paa && mkdir -p /data/media && chown -R paa:paa /data
USER paa
CMD ["python", "-m", "uvicorn", "paa_server.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM node:24.20.0-bookworm-slim AS web-build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY src/web ./src/web
COPY src/ui ./src/ui
COPY src/shared ./src/shared
COPY web.vite.config.ts ./
RUN npm run build:web

FROM caddy:2.10.2-alpine AS web
COPY --from=web-build /app/out/web /srv
COPY deploy/company/Caddyfile /etc/caddy/Caddyfile
