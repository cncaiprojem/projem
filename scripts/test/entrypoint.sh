#!/bin/bash
# Test runner entrypoint script for Task 7.14 integration tests
# This script handles the complex test execution flow in a maintainable way

set -e  # Exit on error
set -o pipefail  # Exit on pipe failure

# Color output for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored messages
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to wait for a service to be ready
wait_for_service() {
    local service_name=$1
    local check_command=$2
    local max_attempts=${3:-30}
    local attempt=1

    log_info "Waiting for $service_name to be ready..."

    while [ $attempt -le $max_attempts ]; do
        if eval "$check_command" 2>/dev/null; then
            log_info "$service_name is ready!"
            return 0
        fi

        echo -n "."
        sleep 2
        ((attempt++))
    done

    echo ""
    log_error "$service_name failed to become ready after $max_attempts attempts"
    return 1
}

# Main execution flow
main() {
    log_info "Starting test runner entrypoint"

    # Wait for PostgreSQL
    wait_for_service "PostgreSQL" \
        "PGPASSWORD=test_password psql -h postgres_test -U freecad_test -d freecad_test -c '\\q'" \
        30

    # Wait for Redis
    wait_for_service "Redis" \
        "redis-cli -h redis_test ping" \
        20

    # Wait for RabbitMQ
    wait_for_service "RabbitMQ" \
        "python -c 'import pika; pika.BlockingConnection(pika.ConnectionParameters(\"rabbitmq_test\"))'" \
        30

    # Wait for MinIO
    wait_for_service "MinIO" \
        "curl -s http://minio_test:9000/minio/health/live" \
        20

    # Wait for FreeCAD container
    wait_for_service "FreeCAD" \
        "curl -s http://freecad_test:8080/health || true" \
        20

    log_info "All services are ready!"

    # Change to app directory
    cd /app

    # Run database migrations
    log_info "Running database migrations..."
    alembic upgrade head

    # Initialize test data based on environment
    if [ "${GENERATE_GOLDEN}" = "true" ]; then
        log_info "Generating golden artefacts..."

        # Golden generation requires FreeCAD - run in freecad_test container
        if [ "${USE_REAL_FREECAD}" = "true" ]; then
            log_info "Using real FreeCAD for golden generation"

            # Check if we're in the container with FreeCAD
            if command -v FreeCADCmd &> /dev/null; then
                python tools/gen_golden.py --regenerate
            else
                log_error "FreeCAD not found in this container. Golden generation requires FreeCAD."
                log_info "Please run golden generation in the freecad_test container:"
                log_info "  docker compose exec freecad_test python /app/tools/gen_golden.py --regenerate"
                exit 1
            fi
        else
            log_warning "USE_REAL_FREECAD is not set. Skipping golden generation."
        fi
    else
        log_info "Initializing test data from existing golden artefacts..."

        # Check if golden manifest exists
        if [ -f "tests/data/golden/golden_manifest.json" ]; then
            log_info "Golden manifest found, using existing artefacts"
        else
            log_warning "No golden manifest found. Tests may fail."
            log_info "Run with GENERATE_GOLDEN=true to generate golden artefacts"
        fi
    fi

    # Run the tests based on TEST_TYPE environment variable
    TEST_TYPE=${TEST_TYPE:-integration}

    case "$TEST_TYPE" in
        unit)
            log_info "Running unit tests..."
            pytest tests/unit -v \
                --junit-xml=/test_results/junit-unit.xml \
                --cov=/app \
                --cov-report=xml:/test_results/coverage-unit.xml
            ;;

        integration)
            log_info "Running integration tests..."
            pytest tests/integration/test_task_7_14_golden_artefacts.py -v \
                --junit-xml=/test_results/junit-integration.xml \
                --cov=/app \
                --cov-report=xml:/test_results/coverage-integration.xml
            ;;

        performance)
            log_info "Running performance tests..."
            pytest tests/performance -v \
                --junit-xml=/test_results/junit-performance.xml
            ;;

        all)
            log_info "Running all tests..."
            pytest tests/ -v \
                --junit-xml=/test_results/junit-all.xml \
                --cov=/app \
                --cov-report=xml:/test_results/coverage-all.xml
            ;;

        golden-verify)
            log_info "Verifying golden artefacts..."
            python tools/gen_golden.py --verify --output=/test_results/golden-verify.json
            ;;

        *)
            log_error "Unknown TEST_TYPE: $TEST_TYPE"
            log_info "Valid options: unit, integration, performance, all, golden-verify"
            exit 1
            ;;
    esac

    # Check test results
    TEST_EXIT_CODE=$?

    if [ $TEST_EXIT_CODE -eq 0 ]; then
        log_info "Tests completed successfully!"
    else
        log_error "Tests failed with exit code: $TEST_EXIT_CODE"

        # Output test report summary if available
        if [ -f "/test_results/junit-${TEST_TYPE}.xml" ]; then
            log_info "Test results saved to /test_results/junit-${TEST_TYPE}.xml"
        fi

        if [ -f "/test_results/coverage-${TEST_TYPE}.xml" ]; then
            log_info "Coverage report saved to /test_results/coverage-${TEST_TYPE}.xml"
        fi
    fi

    exit $TEST_EXIT_CODE
}

# Run main function
main "$@"