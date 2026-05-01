ARG BUILD_FROM=python:3.12-slim
FROM $BUILD_FROM

ARG BUILD_VERSION=0.1.10
ARG BUILD_ARCH=amd64
LABEL io.hass.version="${BUILD_VERSION}" \
    io.hass.type="app" \
    io.hass.arch="${BUILD_ARCH}"

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/

WORKDIR /app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN apt-get update \
    && apt-get install -y --no-install-recommends libopus0 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY config ./config
COPY run.sh /run.sh
RUN chmod a+x /run.sh
RUN uv sync --frozen --no-dev

EXPOSE 8125

CMD ["/run.sh"]
