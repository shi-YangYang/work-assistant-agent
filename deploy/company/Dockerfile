FROM python:3.12.14-slim-bookworm AS service
ARG DEBIAN_MIRROR=https://mirrors.cloud.tencent.com
ARG PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/apps/server:/app/packages/voiceprint-engine/src
RUN sed -i "s|http://deb.debian.org|${DEBIAN_MIRROR}|g" /etc/apt/sources.list.d/debian.sources \
    && apt-get update && apt-get install -y --no-install-recommends ffmpeg=7:5.1.9-0+deb12u1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY apps/server/requirements.lock ./apps/server/requirements.lock
RUN pip install --no-cache-dir --index-url "$PIP_INDEX_URL" -r apps/server/requirements.lock
COPY apps/server/app ./apps/server/app
COPY packages/api-contracts/input-rules.json ./packages/api-contracts/input-rules.json
COPY packages/voiceprint-engine ./packages/voiceprint-engine
RUN useradd --uid 10001 --create-home paa && mkdir -p /data/media && chown -R paa:paa /data
USER paa
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

# The API keeps its lightweight environment; only the worker installs CPU inference.
FROM service AS worker
ARG TORCH_INDEX_URL=https://mirrors.nju.edu.cn/pytorch/whl/cpu
USER root
RUN python -m venv /opt/voiceprints \
    && /opt/voiceprints/bin/pip install --no-cache-dir --index-url "$PIP_INDEX_URL" --extra-index-url "$TORCH_INDEX_URL" 'torch==2.11.0+cpu' 'torchaudio==2.11.0+cpu' \
    && /opt/voiceprints/bin/pip install --no-cache-dir --index-url "$PIP_INDEX_URL" './packages/voiceprint-engine[runtime]' \
    && /opt/voiceprints/bin/python -c 'import torch; assert torch.version.cuda is None'
COPY apps/desktop/resources/models/speaker-community-1/embedding /opt/voiceprint-model
COPY apps/desktop/resources/models/speaker-community-1/LICENSE.txt /opt/voiceprint-model/LICENSE.txt
COPY apps/desktop/resources/models/speaker-community-1/NOTICE.md /opt/voiceprint-model/NOTICE.md
RUN /opt/voiceprints/bin/python -c "from paa_voiceprints import model_file; model_file('/opt/voiceprint-model/pytorch_model.bin')"
ENV PAA_VOICEPRINT_PYTHON=/opt/voiceprints/bin/python PAA_VOICEPRINT_MODEL=/opt/voiceprint-model/pytorch_model.bin
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
RUN npm ci --ignore-scripts --workspace apps/web --include-workspace-root=false --registry="$NPM_REGISTRY" --no-audit --no-fund
COPY apps/web ./apps/web
COPY packages ./packages
COPY tsconfig.base.json ./
RUN npm run build:web

FROM caddy:2.10.2-alpine AS web
COPY --from=web-build /app/apps/web/out /srv
COPY deploy/company/Caddyfile* /etc/caddy/
