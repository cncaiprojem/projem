# syntax=docker/dockerfile:1.7
FROM python:3.13.7-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl git procps tzdata \
    libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock* requirements.txt* /app/

# Tercihen uv/pipx; basitlik için pip
RUN if [ -f requirements.txt ]; then pip install -r requirements.txt; fi

COPY . /app

RUN pip install --no-deps -e .

RUN chmod +x /app/start.sh

EXPOSE 8000

CMD ["/bin/sh", "-c", "./start.sh"]


