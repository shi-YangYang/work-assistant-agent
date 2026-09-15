FROM python:3.12.14-slim-bookworm AS service
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/services/company/src
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY services/company/requirements.lock ./services/company/requirements.lock
RUN pip install --no-cache-dir -r services/company/requirements.lock
COPY services/company/src ./services/company/src
RUN useradd --uid 10001 --create-home paa && mkdir -p /data/media && chown -R paa:paa /data
USER paa
CMD ["python", "-m", "uvicorn", "paa_server.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM node:24.20.0-bookworm-slim AS web-build
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/api-contracts/package.json ./packages/api-contracts/package.json
COPY packages/model-config/package.json ./packages/model-config/package.json
COPY packages/ui-web/package.json ./packages/ui-web/package.json
RUN npm ci --ignore-scripts --workspace apps/web --include-workspace-root=false
COPY apps/web ./apps/web
COPY packages ./packages
COPY tsconfig.base.json ./
RUN npm run build:web

FROM caddy:2.10.2-alpine AS web
COPY --from=web-build /app/apps/web/out /srv
COPY deploy/company/Caddyfile /etc/caddy/Caddyfile
