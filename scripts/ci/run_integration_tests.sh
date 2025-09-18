#!/bin/bash
#
# CI Integration Test Runner for Task 7.14
# This script runs the complete integration test suite with golden artefacts
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="infra/compose/docker-compose.test.yml"
TEST_TIMEOUT=600  # 10 minutes
RESULTS_DIR="test_results"

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Cleanup function
cleanup() {
    print_status "Cleaning up test environment..."
    docker compose -f "$COMPOSE_FILE" down -v --remove-orphans || true

    # Save test results if they exist
    if [ -d "$RESULTS_DIR" ]; then
        print_status "Test results saved to $RESULTS_DIR"
    fi
}

# Set trap for cleanup on exit
trap cleanup EXIT

# Parse command line arguments
RUN_SLOW_TESTS=${RUN_SLOW_TESTS:-false}
TEST_TURKISH_LOCALE=${TEST_TURKISH_LOCALE:-true}
TEST_FILE_UPLOADS=${TEST_FILE_UPLOADS:-true}
TEST_ASSEMBLY4=${TEST_ASSEMBLY4:-true}
REGENERATE_GOLDEN=${REGENERATE_GOLDEN:-false}

while [[ $# -gt 0 ]]; do
    case $1 in
        --slow)
            RUN_SLOW_TESTS=true
            shift
            ;;
        --no-turkish)
            TEST_TURKISH_LOCALE=false
            shift
            ;;
        --no-uploads)
            TEST_FILE_UPLOADS=false
            shift
            ;;
        --no-assembly)
            TEST_ASSEMBLY4=false
            shift
            ;;
        --regenerate-golden)
            REGENERATE_GOLDEN=true
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --slow               Run slow tests"
            echo "  --no-turkish        Skip Turkish locale tests"
            echo "  --no-uploads        Skip file upload tests"
            echo "  --no-assembly       Skip Assembly4 tests"
            echo "  --regenerate-golden Regenerate golden artefacts"
            echo "  --help              Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Export test configuration
export RUN_SLOW_TESTS
export TEST_TURKISH_LOCALE
export TEST_FILE_UPLOADS
export TEST_ASSEMBLY4

# Create results directory
mkdir -p "$RESULTS_DIR"

print_status "Starting integration test environment..."

# Build test images
print_status "Building test images..."
docker compose -f "$COMPOSE_FILE" build --no-cache

# Start services
print_status "Starting test services..."
docker compose -f "$COMPOSE_FILE" up -d postgres_test redis_test minio_test rabbitmq_test freecad_test

# Wait for services to be healthy
print_status "Waiting for services to be healthy..."
TIMEOUT=60
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    if docker compose -f "$COMPOSE_FILE" ps | grep -q "unhealthy\|starting"; then
        sleep 5
        ELAPSED=$((ELAPSED + 5))
        echo -n "."
    else
        echo ""
        print_status "All services are healthy!"
        break
    fi
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    print_error "Services failed to become healthy within $TIMEOUT seconds"
    docker compose -f "$COMPOSE_FILE" ps
    exit 1
fi

# Initialize MinIO buckets
print_status "Initializing MinIO buckets..."
docker compose -f "$COMPOSE_FILE" exec -T minio_test mc alias set local http://localhost:9000 minioadmin minioadmin
docker compose -f "$COMPOSE_FILE" exec -T minio_test mc mb local/test-artefacts --ignore-existing
docker compose -f "$COMPOSE_FILE" exec -T minio_test mc mb local/test-golden --ignore-existing
docker compose -f "$COMPOSE_FILE" exec -T minio_test mc mb local/test-logs --ignore-existing

# Initialize RabbitMQ queues
print_status "Initializing RabbitMQ queues..."
docker compose -f "$COMPOSE_FILE" exec -T rabbitmq_test rabbitmqctl await_startup

# Regenerate golden artefacts if requested
if [ "$REGENERATE_GOLDEN" = true ]; then
    print_status "Regenerating golden artefacts..."
    docker compose -f "$COMPOSE_FILE" run --rm test_runner python tools/gen_golden.py --regenerate
fi

# Run integration tests
print_status "Running integration tests..."
TEST_EXIT_CODE=0
timeout "$TEST_TIMEOUT" docker compose -f "$COMPOSE_FILE" run --rm test_runner || TEST_EXIT_CODE=$?

# Copy test results
print_status "Collecting test results..."
CONTAINER_ID=$(docker compose -f "$COMPOSE_FILE" ps -q test_runner 2>/dev/null || echo "")
if [ -n "$CONTAINER_ID" ]; then
    docker cp "$CONTAINER_ID:/test_results/." "$RESULTS_DIR/" 2>/dev/null || true
fi

# Print test summary
if [ -f "$RESULTS_DIR/junit.xml" ]; then
    print_status "Test results available in $RESULTS_DIR/junit.xml"
fi

if [ -f "$RESULTS_DIR/coverage.xml" ]; then
    COVERAGE=$(grep 'line-rate' "$RESULTS_DIR/coverage.xml" | sed 's/.*line-rate="\([^"]*\)".*/\1/' | head -1)
    if [ -n "$COVERAGE" ]; then
        COVERAGE_PCT=$(echo "$COVERAGE * 100" | bc -l | xargs printf "%.2f")
        print_status "Test coverage: ${COVERAGE_PCT}%"
    fi
fi

# Check test exit code
if [ $TEST_EXIT_CODE -eq 0 ]; then
    print_status "All tests passed successfully!"
else
    print_error "Tests failed with exit code: $TEST_EXIT_CODE"

    # Print logs for debugging
    print_warning "Showing recent logs for debugging:"
    docker compose -f "$COMPOSE_FILE" logs --tail=50
fi

exit $TEST_EXIT_CODE
