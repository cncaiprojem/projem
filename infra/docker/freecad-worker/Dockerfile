# syntax=docker/dockerfile:1.9
# ==============================================================================
# FREECAD WORKER CONTAINER - TASK 7.5
# ==============================================================================
# Multi-stage production-ready FreeCAD 1.1.0 worker container with:
# - AppImage-based FreeCAD 1.1.0 with SHA256 verification
# - Python requirements (numpy, trimesh, pygltflib, minio, psutil)
# - Worker harness with health checks, resource monitoring, TechDraw integration
# - Headless operation optimized for container environments
# - Security hardening with non-root execution
# ==============================================================================

# Build argument for FreeCAD AppImage SHA256 verification
# IMPORTANT: This is a placeholder that will cause build to fail safely
# TODO: Replace with actual FreeCAD 1.1.0 AppImage SHA256 hash
ARG FREECAD_SHA256=REPLACE_ME_WITH_ACTUAL_FREECAD_SHA256_BEFORE_DEPLOYMENT

# ==============================================================================
# BUILDER STAGE - FreeCAD AppImage and Python wheels
# ==============================================================================
FROM debian:bookworm AS builder

# Build-time metadata
LABEL stage=builder
LABEL maintainer="FreeCAD Platform Team"
LABEL description="FreeCAD 1.1.0 worker builder stage"

# Builder environment
ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core build tools
    curl \
    ca-certificates \
    # Python build dependencies
    python3 \
    python3-pip \
    python3-dev \
    python3-venv \
    build-essential \
    # AppImage extraction dependencies  
    fuse \
    file \
    # Cleanup
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Create build environment
WORKDIR /build

# Copy requirements for Python wheel building
COPY requirements.txt /build/

# Build Python wheels
RUN python3 -m pip install --upgrade pip wheel && \
    python3 -m pip wheel -r requirements.txt --wheel-dir=/build/wheels

# Download and verify FreeCAD 1.1.0 AppImage
ARG FREECAD_SHA256
RUN curl -L -o FreeCAD_1.1.0.AppImage \
    "https://github.com/FreeCAD/FreeCAD/releases/download/1.1.0/FreeCAD_1.1.0-Linux-x86_64.AppImage" && \
    echo "${FREECAD_SHA256}  FreeCAD_1.1.0.AppImage" | sha256sum -c - && \
    chmod +x FreeCAD_1.1.0.AppImage

# Extract AppImage
RUN ./FreeCAD_1.1.0.AppImage --appimage-extract && \
    mv squashfs-root /opt/freecad && \
    # Cleanup extraction artifacts
    rm -f FreeCAD_1.1.0.AppImage

# Strip symbols for size reduction (safe for headless operation)
RUN find /opt/freecad -type f -executable -exec strip --strip-unneeded {} + 2>/dev/null || true

# ==============================================================================
# RUNTIME STAGE - Optimized headless container
# ==============================================================================
FROM debian:bookworm-slim AS runtime

# Runtime metadata
LABEL maintainer="FreeCAD Platform Team" \
      version="1.1.0" \
      description="FreeCAD 1.1.0 worker container with TechDraw and resource monitoring" \
      security.scan="enabled" \
      compliance.level="enterprise" \
      task="7.5"

# Runtime environment for headless operation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    # FreeCAD headless configuration
    FC_NO_UI=1 \
    QT_QPA_PLATFORM=offscreen \
    QT_LOGGING_RULES="*.debug=false" \
    # Threading optimization 
    OMP_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    # Locale
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    TZ=UTC \
    # FreeCAD paths
    PATH=/opt/freecad/usr/bin:$PATH \
    PYTHONPATH=/app:/opt/freecad/usr/lib/python3.11/site-packages \
    LD_LIBRARY_PATH=/opt/freecad/usr/lib:/opt/freecad/usr/lib/x86_64-linux-gnu \
    # Health server configuration
    HEALTH_SERVER=1 \
    HEALTH_PORT=8080

# Install minimal runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core runtime
    python3 \
    python3-pip \
    # Essential graphics libraries for headless FreeCAD (minimal set)
    libgl1-mesa-glx \
    libglu1-mesa \
    libxrender1 \
    libxext6 \
    libx11-6 \
    libxfixes3 \
    # Font rendering for TechDraw
    libfontconfig1 \
    libfreetype6 \
    fonts-dejavu-core \
    fonts-liberation \
    # System utilities
    ca-certificates \
    curl \
    procps \
    # Cleanup
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Copy FreeCAD from builder stage
COPY --from=builder /opt/freecad /opt/freecad

# Create symlinks for FreeCAD binaries
RUN ln -sf /opt/freecad/usr/bin/FreeCAD /usr/local/bin/FreeCAD && \
    ln -sf /opt/freecad/usr/bin/FreeCADCmd /usr/local/bin/FreeCADCmd

# Copy Python wheels and install
COPY --from=builder /build/wheels /tmp/wheels
RUN python3 -m pip install --no-cache-dir /tmp/wheels/*.whl && \
    rm -rf /tmp/wheels

# Create non-root user for security
RUN groupadd -g 10001 freecad && \
    useradd -u 10001 -g freecad -m -s /bin/bash freecad && \
    # Create working directories
    mkdir -p /app /work /tmp/freecad && \
    chown -R freecad:freecad /app /work /tmp/freecad

# Copy worker harness and templates
COPY --chown=freecad:freecad worker_script.py /app/
COPY --chown=freecad:freecad templates/ /app/templates/

# Create required directories for worker operation
RUN mkdir -p /app/logs /app/temp && \
    chown -R freecad:freecad /app

# Switch to non-root user
USER freecad
WORKDIR /work

# Expose health check port
EXPOSE 8080

# Validate FreeCAD installation
RUN FreeCADCmd --version 2>&1 | grep -q "1.1.0" || exit 1

# Health check for container orchestration
HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=120s \
    CMD curl -f http://localhost:${HEALTH_PORT}/health/freecad || exit 1

# Default entrypoint - FreeCAD worker harness
ENTRYPOINT ["FreeCADCmd", "-c", "/app/worker_script.py"]
CMD ["--help"]

# ==============================================================================
# SECURITY AND COMPLIANCE NOTES:
# - Runs as non-root user (UID 10001)
# - Uses official FreeCAD 1.1.0 AppImage with SHA256 verification
# - Minimal attack surface with only essential runtime dependencies
# - Headless configuration prevents GUI-based vulnerabilities  
# - Read-only root filesystem compatible
# - Resource monitoring via psutil
# - Health checks for container orchestration
# - Multi-stage build reduces final image size
# ==============================================================================

# ==============================================================================
# USAGE EXAMPLES:
#
# Build:
#   docker build -t freecad-worker:1.1.0 .
#
# Version check:
#   docker run --rm freecad-worker:1.1.0 --version
#
# Health check test:
#   docker run --rm -p 8080:8080 freecad-worker:1.1.0 --health-server
#
# Model generation:
#   docker run --rm -v /data:/work freecad-worker:1.1.0 \
#     --flow prompt --input /work/input.json --outdir /work/out \
#     --request-id uuid --cpu-seconds 600 --mem-mb 2048
#
# TechDraw generation:
#   docker run --rm -v /data:/work freecad-worker:1.1.0 \
#     --flow params --input /work/input.json --outdir /work/out \
#     --techdraw on --td-template /app/templates/A4_Landscape.svg
# ==============================================================================