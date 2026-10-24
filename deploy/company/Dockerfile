# syntax=docker/dockerfile:1
FROM python:3.12.14-slim-bookworm AS base
ARG DEBIAN_MIRROR=https://mirrors.cloud.tencent.com
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/server:/app/packages/voiceprint-engine/src
RUN rm -f /etc/apt/apt.conf.d/docker-clean \
    && sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources
RUN --mount=type=cache,id=company-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=company-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1
WORKDIR /app
RUN useradd --uid 10001 --create-home paa && mkdir -p /data/media && chown -R paa:paa /data

FROM base AS service-deps
COPY apps/server/requirements.lock ./apps/server/requirements.lock
RUN --mount=type=cache,id=company-pip,target=/root/.cache/pip \
    python -m venv /opt/server \
    && /opt/server/bin/pip install --index-url "$PIP_INDEX_URL" -r apps/server/requirements.lock

FROM service-deps AS service
ENV PATH=/opt/server/bin:$PATH
COPY apps/server/app ./apps/server/app
COPY packages/api-contracts/input-rules.json ./packages/api-contracts/input-rules.json
COPY packages/voiceprint-engine/pyproject.toml ./packages/voiceprint-engine/pyproject.toml
COPY packages/voiceprint-engine/src ./packages/voiceprint-engine/src
USER paa
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# Neither business source nor API dependency changes invalidate these heavy layers.
FROM base AS worker-deps
ARG TORCH_INDEX_URL=https://mirrors.nju.edu.cn/pytorch/whl/cpu
ARG LIBREOFFICE_VERSION=4:7.4.7-1+deb12u14
RUN --mount=type=cache,id=company-apt-cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,id=company-apt-lists,target=/var/lib/apt/lists,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer="$LIBREOFFICE_VERSION" libreoffice-calc="$LIBREOFFICE_VERSION" libreoffice-impress="$LIBREOFFICE_VERSION" \
    procps fonts-liberation fonts-noto-cjk poppler-utils
COPY deploy/company/requirements-voiceprints.lock /opt/requirements-voiceprints.lock
RUN --mount=type=cache,id=company-pip,target=/root/.cache/pip \
    python -m venv /opt/voiceprints \
    && /opt/voiceprints/bin/pip install --no-deps --index-url "$PIP_INDEX_URL" --extra-index-url "$TORCH_INDEX_URL" -r /opt/requirements-voiceprints.lock \
    && /opt/voiceprints/bin/pip check \
    && /opt/voiceprints/bin/python -c 'import torch; assert torch.version.cuda is None'
COPY packages/voiceprint-engine/resources/models/speaker-community-1/embedding /opt/voiceprint-model
COPY packages/voiceprint-engine/resources/models/speaker-community-1/LICENSE.txt /opt/voiceprint-model/LICENSE.txt
COPY packages/voiceprint-engine/resources/models/speaker-community-1/NOTICE.md /opt/voiceprint-model/NOTICE.md

FROM worker-deps AS worker
COPY --from=service-deps /opt/server /opt/server
COPY --from=service /app /app
RUN /opt/voiceprints/bin/pip install --no-deps --no-build-isolation './packages/voiceprint-engine[runtime]' \
    && /opt/voiceprints/bin/python -c "from paa_voiceprints import model_file; model_file('/opt/voiceprint-model/pytorch_model.bin')"
ENV PATH=/opt/server/bin:$PATH PAA_VOICEPRINT_PYTHON=/opt/voiceprints/bin/python PAA_VOICEPRINT_MODEL=/opt/voiceprint-model/pytorch_model.bin
USER paa
CMD ["python", "-m", "app.worker"]

FROM node:24.20.0-bookworm-slim AS web-build
ARG NPM_REGISTRY=https://registry.npmmirror.com
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json ./apps/web/package.json
COPY packages/api-contracts/package.json ./packages/api-contracts/package.json
COPY packages/model-config/package.json ./packages/model-config/package.json
COPY packages/ui-web/package.json ./packages/ui-web/package.json
RUN --mount=type=cache,id=company-npm,target=/root/.npm \
    npm ci --ignore-scripts --workspace apps/web --include-workspace-root=false --registry="$NPM_REGISTRY" --no-audit --no-fund
COPY apps/web ./apps/web
COPY packages/api-contracts ./packages/api-contracts
COPY packages/model-config ./packages/model-config
COPY packages/ui-web ./packages/ui-web
COPY tsconfig.base.json ./
RUN npm run build:web

FROM caddy:2.10.2-alpine AS web
COPY --from=web-build /app/apps/web/out /srv
COPY deploy/company/Caddyfile* /etc/caddy/
