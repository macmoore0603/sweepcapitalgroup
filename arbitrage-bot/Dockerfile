# arbbot: scanner / paper / live trading bot. Default: `scan` with a mounted config.
#   docker build -t arbbot .
#   docker run --rm -v "$PWD/config.toml:/config/config.toml:ro" -v "$PWD/logs:/app/logs" arbbot
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY pyproject.toml ./
COPY arbbot ./arbbot
RUN pip install . \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin arbbot \
    && mkdir -p /app/logs /app/data /config \
    && chown arbbot:arbbot /app/logs /app/data

USER arbbot
VOLUME ["/app/logs", "/app/data"]

# SIGTERM (docker stop) shuts down gracefully: feeds stop, in-flight orders finish.
STOPSIGNAL SIGTERM
ENTRYPOINT ["arbbot"]
CMD ["scan", "--config", "/config/config.toml"]
