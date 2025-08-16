# syntax=docker/dockerfile:1.7

# ==============================================================================
# Multi-stage Dockerfile for FastAPI Backend
# ==============================================================================

# ------------------------------------------------------------------------------
# Builder Stage: Compile dependencies and prepare wheels
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS builder

# Enable BuildKit features
LABEL maintainer="FreeCAD Platform Team"
LABEL description="FastAPI backend for FreeCAD-based CNC/CAM/CAD platform"

# Build environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=100

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    pkg-config \
    libpq-dev \
    libcairo2-dev \
    libpango1.0-dev \
    libgdk-pixbuf-2.0-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy dependency files first for optimal layer caching
COPY requirements.txt pyproject.toml* ./

# Create virtual environment and install dependencies
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Use pip cache mount for faster builds with BuildKit
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip setuptools wheel && \
    if [ -f requirements.txt ]; then \
        pip install --no-deps -r requirements.txt && \
        pip install --editable .; \
    elif [ -f pyproject.toml ]; then \
        pip install .; \
    else \
        echo "No requirements.txt or pyproject.toml found" && exit 1; \
    fi

# ------------------------------------------------------------------------------
# Runtime Stage: Minimal production image
# ------------------------------------------------------------------------------
FROM python:3.11-slim-bookworm AS runtime

# Runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app:$PYTHONPATH"

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client library
    libpq5 \
    # Health check utilities
    curl \
    netcat-traditional \
    # Cairo/Pango runtime libraries for report generation
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    # Font support
    fonts-dejavu-core \
    # Timezone data
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user and group
RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --shell /bin/bash --create-home app

# Set up application directory
WORKDIR /app

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=app:app . /app/

# Make startup script executable
RUN chmod +x /app/start.sh

# Security: Drop all capabilities and enable read-only root filesystem where possible
# Note: Some capabilities may be needed for specific operations, adjust as needed
USER app:app

# Expose application port
EXPOSE 8000

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f http://localhost:8000/api/v1/healthz || exit 1

# Default command using startup script (ensures DB waiting and migrations)
CMD ["/app/start.sh"]


