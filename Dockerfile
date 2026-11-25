# Imua — Multi-stage Docker build
# Stage 1: Build dependencies
FROM python:3.13-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY requirements-base.txt .
RUN pip install --no-cache-dir --user -r requirements-base.txt

# Stage 2: Runtime
FROM python:3.13-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -r imua && useradd -r -g imua -d /home/imua -s /bin/false imua

WORKDIR /app

COPY --from=builder /root/.local /home/imua/.local
ENV HOME=/home/imua
ENV PATH=/home/imua/.local/bin:$PATH

COPY config/ config/
COPY app/ app/
# scripts/: create_admin.py (first admin, password reset) and the git post-receive hook
COPY scripts/ scripts/

RUN mkdir -p data/database data/repos data/docs data/chroma \
    && chown -R imua:imua /app /home/imua

USER imua

EXPOSE 47280

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:47280/api/health || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:47280", "--workers", "1", "app.server:app"]
