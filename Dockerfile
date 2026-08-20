FROM python:3.13.7-slim-bookworm AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --prefix=/install .

FROM python:3.13.7-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ZENITH_QDRANT_URL=http://qdrant:6333 \
    ZENITH_VAULT_PATH=/vault \
    ZENITH_MODEL_CACHE_PATH=/models \
    ZENITH_HOST=0.0.0.0 \
    ZENITH_PORT=8080

RUN groupadd --system --gid 10001 zenith \
    && useradd --system --uid 10001 --gid zenith --home-dir /app zenith \
    && mkdir -p /app /models \
    && chown -R zenith:zenith /app /models

COPY --from=builder /install /usr/local
WORKDIR /app
USER zenith

EXPOSE 8080
CMD ["zenith", "serve"]
