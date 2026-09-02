FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_PATH=/app/data/nodeseek_monitor.db

WORKDIR /app

RUN groupadd --system bot && useradd --system --gid bot --home-dir /app bot

COPY pyproject.toml README.md ./
COPY src ./src
COPY config.example.yaml ./config.yaml

RUN pip install . && mkdir -p /app/data /app/logs && chown -R bot:bot /app

USER bot

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,sqlite3; c=sqlite3.connect(os.environ['DATABASE_PATH']); c.execute('SELECT 1'); c.close()"

CMD ["python", "-m", "nodeseek_bot"]
