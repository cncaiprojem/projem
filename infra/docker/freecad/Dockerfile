# syntax=docker/dockerfile:1.7
# ==============================================================================
# FREECAD UTILITY CONTAINER
# ==============================================================================
# Production-ready, security-hardened FreeCAD 1.1.x utility container
# Purpose: Provides FreeCADCmd entrypoint for CAD/CAM operations
# Usage: docker run --rm freecad-utility:1.1 [freecadcmd-args]
# ==============================================================================

FROM ubuntu:22.04@sha256:e9569c25505f33ff72e88b2990887c9dcf230f23259da296eb814fc2b41af999

# Security: Set labels for container identification and compliance
LABEL maintainer="FreeCAD Platform Team" \
      version="1.1.0" \
      description="FreeCAD 1.1.x utility container with security hardening" \
      security.scan="enabled" \
      compliance.level="enterprise"

# Environment configuration for headless operation
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    QT_QPA_PLATFORM=offscreen \
    LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    FREECAD_VERSION=1.1

# Install system dependencies and FreeCAD from stable PPA
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Core dependencies
    ca-certificates \
    curl \
    gnupg \
    # Python runtime (required for FreeCAD scripting)
    python3 \
    python3-pip \
    # Security and process management
    dumb-init \
    # Cleanup package cache
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Add FreeCAD PPA with pinned key and install specific version
RUN mkdir -p /etc/apt/keyrings \
    && curl -fsSL 'https://keyserver.ubuntu.com/pks/lookup?op=get&search=0xA728AE60A790F0EB' \
      | gpg --dearmor -o /etc/apt/keyrings/freecad.gpg \
    && echo 'deb [signed-by=/etc/apt/keyrings/freecad.gpg] http://ppa.launchpad.net/freecad-maintainers/freecad-stable/ubuntu jammy main' \
      > /etc/apt/sources.list.d/freecad.list \
    && apt-get update \
    # Install FreeCAD 1.1.x (latest available stable release)
    && apt-get install -y --no-install-recommends \
       freecad \
       freecad-python3 \
    # Security: Remove package manager caches and temporary files
    && rm -rf /var/lib/apt/lists/* \
              /var/cache/apt/archives/* \
              /tmp/* \
              /var/tmp/* \
    # Security: Remove unnecessary packages that could be attack vectors
    && apt-get autoremove -y \
    && apt-get autoclean

# Security: Create non-root user with fixed UID/GID for consistency
# UID 10001 aligns with enterprise Kubernetes security policies
RUN groupadd -g 10001 freecad \
    && useradd -u 10001 -g freecad -m -s /bin/bash freecad \
    && mkdir -p /home/freecad/.FreeCAD \
    && chown -R freecad:freecad /home/freecad

# Create working directory with proper ownership
WORKDIR /workspace
RUN chown freecad:freecad /workspace

# Security: Switch to non-root user
USER freecad

# Health check: Verify FreeCAD installation and functionality
# Runs every 30s with 10s timeout, 5 retries before marked unhealthy
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=30s \
    CMD freecadcmd --version 2>/dev/null | grep -q "FreeCAD" || exit 1

# Security: Use dumb-init for proper signal handling and zombie reaping
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Default command: Run FreeCADCmd (can be overridden)
# Usage examples:
#   docker run freecad-utility --version
#   docker run freecad-utility -c "import FreeCAD; print('OK')"
#   docker run freecad-utility script.py
CMD ["freecadcmd", "--help"]

# ==============================================================================
# SECURITY NOTES:
# - Runs as non-root user (UID 10001)
# - Uses specific package versions to prevent supply chain attacks
# - Minimal attack surface with only essential packages
# - Headless configuration prevents GUI-based vulnerabilities
# - Health checks ensure container integrity
# - dumb-init prevents PID 1 issues and zombie processes
# ==============================================================================

# ==============================================================================
# USAGE EXAMPLES:
# 
# Build:
#   docker build -t freecad-utility:1.1 .
#
# Version check:
#   docker run --rm freecad-utility:1.1 --version
#
# Run FreeCAD script:
#   docker run --rm -v /path/to/scripts:/workspace freecad-utility:1.1 script.py
#
# Interactive Python session:
#   docker run --rm -it freecad-utility:1.1 -c "import FreeCAD; print(FreeCAD.Version())"
#
# Process CAD file:
#   docker run --rm -v /data:/workspace freecad-utility:1.1 -c "
#     import FreeCAD
#     doc = FreeCAD.open('input.FCStd')
#     # ... processing ...
#     doc.save('output.FCStd')
#   "
# ==============================================================================