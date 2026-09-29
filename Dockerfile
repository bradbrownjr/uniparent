# ---- build the PWA ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UNIPARENT_DB=/data/uniparent.db \
    UNIPARENT_STATIC=/app/static \
    PORT=8095
WORKDIR /app
COPY backend/pyproject.toml ./
COPY backend/uniparent ./uniparent
RUN pip install . && rm -rf build *.egg-info
COPY --from=web /web/dist ./static
# Unraid convention: nobody (99) : users (100) owns appdata.
RUN groupadd -o -g 100 users 2>/dev/null || true \
 && useradd -r -u 99 -g 100 -d /app -s /usr/sbin/nologin uniparent \
 && mkdir -p /data && chown 99:100 /data
USER 99:100
VOLUME /data
EXPOSE 8095
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health', timeout=4)"
CMD ["uniparent", "serve"]
