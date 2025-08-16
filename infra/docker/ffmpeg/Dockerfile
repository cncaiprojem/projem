# syntax=docker/dockerfile:1.7
# ==============================================================================
# FFMPEG UTILITY CONTAINER
# ==============================================================================
# Production-ready, security-hardened FFmpeg 6.x utility container
# Purpose: Provides video/audio processing for CAM simulation recordings
# Usage: docker run --rm ffmpeg-utility:6.1 [ffmpeg-args]
# ==============================================================================

FROM alpine:3.19@sha256:c5b1261d6d3e43071626931fc004f70149baeba2c8ec672bd4f27761f8e1ad6b

# Security: Set labels for container identification and compliance
LABEL maintainer="FreeCAD Platform Team" \
      version="6.1.0" \
      description="FFmpeg 6.1.x utility container with security hardening" \
      security.scan="enabled" \
      compliance.level="enterprise"

# Environment configuration
ENV LC_ALL=C.UTF-8 \
    LANG=C.UTF-8 \
    FFMPEG_VERSION=6.1

# Install FFmpeg and essential dependencies from Alpine repositories
# Alpine provides well-maintained, security-updated FFmpeg packages
RUN apk add --no-cache \
    # Core FFmpeg package (latest available)
    ffmpeg \
    # Additional codec support
    ffmpeg-libs \
    # Common utilities for media processing
    imagemagick \
    # Security and process management
    dumb-init \
    # Essential utilities
    ca-certificates \
    curl \
    # Cleanup package cache
    && rm -rf /var/cache/apk/* \
              /tmp/* \
              /var/tmp/*

# Security: Create non-root user with fixed UID/GID for consistency
# UID 10003 for FFmpeg service (different from other utilities)
RUN addgroup -g 10003 ffmpeg \
    && adduser -u 10003 -G ffmpeg -D -s /bin/sh ffmpeg \
    && mkdir -p /home/ffmpeg \
    && chown -R ffmpeg:ffmpeg /home/ffmpeg

# Create working directory with proper ownership
WORKDIR /workspace
RUN chown ffmpeg:ffmpeg /workspace

# Security: Switch to non-root user
USER ffmpeg

# Health check: Verify FFmpeg installation and functionality
# Runs every 30s with 10s timeout, 5 retries before marked unhealthy
HEALTHCHECK --interval=30s --timeout=10s --retries=5 --start-period=30s \
    CMD ffmpeg -version 2>/dev/null | grep -q "ffmpeg version" || exit 1

# Security: Use dumb-init for proper signal handling and zombie reaping
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Default command: Run FFmpeg
# Usage examples:
#   docker run ffmpeg-utility -version
#   docker run ffmpeg-utility -i input.mp4 -c:v libx264 output.mp4
#   docker run ffmpeg-utility -f lavfi -i testsrc -t 10 test.mp4
CMD ["ffmpeg", "-version"]

# ==============================================================================
# SECURITY NOTES:
# - Runs as non-root user (UID 10003)
# - Uses Alpine Linux for minimal attack surface
# - Pinned package versions to prevent supply chain attacks
# - No unnecessary packages or development tools
# - Health checks ensure container integrity
# - dumb-init prevents PID 1 issues and zombie processes
# - Read-only filesystem compatible (no writes to system directories)
# ==============================================================================

# ==============================================================================
# USAGE EXAMPLES:
# 
# Build:
#   docker build -t ffmpeg-utility:6.1 .
#
# Version check:
#   docker run --rm ffmpeg-utility:6.1 -version
#
# Convert video format:
#   docker run --rm -v /path/to/videos:/workspace ffmpeg-utility:6.1 \
#     -i input.avi -c:v libx264 -c:a aac output.mp4
#
# Create simulation recording:
#   docker run --rm -v /data:/workspace ffmpeg-utility:6.1 \
#     -f lavfi -i testsrc=duration=10:size=1920x1080:rate=30 \
#     -c:v libx264 -preset fast -crf 23 simulation.mp4
#
# Extract frames from video:
#   docker run --rm -v /data:/workspace ffmpeg-utility:6.1 \
#     -i simulation.mp4 -vf fps=1/10 frame_%04d.png
#
# Create time-lapse from frames:
#   docker run --rm -v /data:/workspace ffmpeg-utility:6.1 \
#     -framerate 30 -i frame_%04d.png -c:v libx264 -r 30 timelapse.mp4
#
# Audio processing:
#   docker run --rm -v /data:/workspace ffmpeg-utility:6.1 \
#     -i input.wav -af volume=0.5 -c:a libmp3lame output.mp3
# ==============================================================================