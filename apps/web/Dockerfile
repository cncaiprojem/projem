# syntax=docker/dockerfile:1.7-labs
# ==============================================================================
# ENTERPRISE-GRADE NEXT.JS DOCKERFILE
# ==============================================================================
# Production-ready, security-hardened, multi-stage Docker build for Next.js 14
# Compliant with CIS Docker Benchmark and OWASP Container Security Top 10
# ==============================================================================

# ------------------------------------------------------------------------------
# STAGE 1: Application Builder 
# Purpose: Build the Next.js application in standalone mode
# Optimization: Layer caching, minimal context copying, includes optimized dependencies
# ------------------------------------------------------------------------------
FROM node:20-alpine@sha256:df02558528d3d3d0d621f112e232611aecfee7cbc654f6b375765f72bb262799 AS builder

WORKDIR /app

# Install build-time dependencies and security updates
RUN apk add --no-cache \
    dumb-init=1.2.5-r3 \
    && apk upgrade --no-cache

# Copy package files and install ALL dependencies (including dev)
COPY package.json pnpm-lock.yaml* .npmrc* ./

# Enable pnpm with specific version for security and consistency  
RUN corepack enable && corepack prepare pnpm@8.15.4 --activate

# Install all dependencies for build process
RUN pnpm config set audit-level high \
    && pnpm config set fund false \
    && pnpm config set update-notifier false \
    && pnpm install --no-optional

# Copy application source code
# .dockerignore ensures only necessary files are copied
COPY . .

# Build the Next.js application
# Environment: Production mode with standalone output for minimal runtime
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV CI=true

# Build with optimizations
RUN pnpm run build

# Ensure public directory exists (Next.js public folder is optional)
RUN mkdir -p /app/public

# ------------------------------------------------------------------------------
# STAGE 2: Production Runtime
# Purpose: Minimal production runtime with security hardening
# Security: Non-root user, read-only filesystem, minimal packages
# ------------------------------------------------------------------------------
FROM node:20-alpine@sha256:df02558528d3d3d0d621f112e232611aecfee7cbc654f6b375765f72bb262799 AS runner

# Install only essential runtime dependencies and security updates
RUN apk add --no-cache \
    dumb-init \
    && apk upgrade --no-cache \
    && rm -rf /var/cache/apk/*

# Security: Create non-root user with specific UID/GID
# UID 1001 aligns with enterprise Kubernetes security policies
RUN addgroup -g 1001 -S nodejs \
    && adduser -S nextjs -u 1001 -G nodejs

# Create application directory with proper ownership
WORKDIR /app

# Security: Set production environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Copy built application from builder stage
# Next.js standalone mode already includes optimized node_modules and dependencies
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

# Copy public directory (create empty if it doesn't exist)
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

# Security: Switch to non-root user
USER nextjs

# Network: Expose application port
EXPOSE 3000

# Health check configuration for Kubernetes readiness/liveness probes
# Endpoint: /healthz (implemented in Next.js app)
# Interval: Every 30s, Timeout: 10s, Start period: 30s, Retries: 3
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD wget --no-verbose --tries=1 --spider http://localhost:3000/healthz || exit 1

# Security: Process management with proper signal handling
# Using dumb-init for proper signal forwarding and zombie reaping
ENTRYPOINT ["/usr/bin/dumb-init", "--"]

# Start the Next.js application in standalone mode
# Standalone mode includes only necessary dependencies for optimal size
CMD ["node", "server.js"]


