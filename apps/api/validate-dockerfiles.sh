#!/usr/bin/env bash
# Dockerfile validation script
set -euo pipefail

echo "=== Docker Setup Validation ==="
echo

# Check Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed or not in PATH"
    exit 1
fi
echo "✅ Docker is available"

# Check BuildKit support
echo "🔧 Checking BuildKit support..."
if docker buildx version &> /dev/null; then
    echo "✅ BuildKit is available"
else
    echo "⚠️  BuildKit not available, using legacy build"
fi

echo

# Validate Dockerfile syntax
echo "🔍 Validating Dockerfile syntax..."

echo "  Checking Dockerfile (API)..."
if docker run --rm -i hadolint/hadolint < Dockerfile &> /dev/null; then
    echo "  ✅ Dockerfile syntax OK"
else
    echo "  ⚠️  Dockerfile has syntax warnings (check with hadolint)"
fi

echo "  Checking Dockerfile.workers..."
if docker run --rm -i hadolint/hadolint < Dockerfile.workers &> /dev/null; then
    echo "  ✅ Dockerfile.workers syntax OK"
else
    echo "  ⚠️  Dockerfile.workers has syntax warnings (check with hadolint)"
fi

echo

# Check required files
echo "🔍 Checking required files..."

REQUIRED_FILES=(
    "requirements.txt"
    "pyproject.toml"
    "start.sh"
    "start-worker.sh"
    "start-beat.sh"
    ".dockerignore"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✅ $file exists"
    else
        echo "  ❌ $file missing"
    fi
done

echo

# Check startup script permissions
echo "🔍 Checking startup script permissions..."
for script in start.sh start-worker.sh start-beat.sh; do
    if [ -x "$script" ]; then
        echo "  ✅ $script is executable"
    else
        echo "  ❌ $script is not executable"
    fi
done

echo

# Validate environment variables in scripts
echo "🔍 Validating environment variables..."

echo "  Checking start.sh..."
if grep -q "PYTHONPATH\|DATABASE_URL\|ENV" start.sh; then
    echo "  ✅ start.sh has required environment variables"
else
    echo "  ⚠️  start.sh may be missing environment variables"
fi

echo "  Checking start-worker.sh..."
if grep -q "WORKER_QUEUES\|PYTHONPATH" start-worker.sh; then
    echo "  ✅ start-worker.sh has required environment variables"
else
    echo "  ⚠️  start-worker.sh may be missing environment variables"
fi

echo "  Checking start-beat.sh..."
if grep -q "BEAT_LOGLEVEL\|PYTHONPATH" start-beat.sh; then
    echo "  ✅ start-beat.sh has required environment variables"
else
    echo "  ⚠️  start-beat.sh may be missing environment variables"
fi

echo

# Test build (dry run)
echo "🚀 Testing Docker builds (syntax only)..."

echo "  Testing API Dockerfile..."
if docker build --dry-run -f Dockerfile . &> /dev/null; then
    echo "  ✅ API Dockerfile build syntax OK"
else
    echo "  ❌ API Dockerfile build syntax error"
fi

echo "  Testing Workers Dockerfile..."
if docker build --dry-run -f Dockerfile.workers . &> /dev/null; then
    echo "  ✅ Workers Dockerfile build syntax OK"
else
    echo "  ❌ Workers Dockerfile build syntax error"
fi

echo

echo "=== Validation Complete ==="
echo
echo "📋 Next Steps:"
echo "1. Run: docker build -f Dockerfile -t freecad-api:latest ."
echo "2. Run: docker build -f Dockerfile.workers -t freecad-workers:latest ."
echo "3. Test containers with appropriate environment variables"
echo "4. Update docker-compose.yml to use new Dockerfiles"