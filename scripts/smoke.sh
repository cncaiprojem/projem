#!/bin/bash

# ==============================================================================
# FREECAD PLATFORM DEVELOPMENT SMOKE TEST SCRIPT
# ==============================================================================
# Comprehensive smoke test suite for development docker-compose stack
# Tests all services, health endpoints, and critical functionality
# Usage: ./scripts/smoke.sh [--timeout=300] [--verbose] [--skip-utilities]
# ==============================================================================

set -euo pipefail

# =============================================================================
# CONFIGURATION AND DEFAULTS
# =============================================================================

# Script metadata
SCRIPT_NAME="FreeCAD Platform Development Smoke Test"
SCRIPT_VERSION="1.0.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Default configuration
DEFAULT_TIMEOUT=300
DEFAULT_COMPOSE_FILE="${PROJECT_ROOT}/infra/compose/docker-compose.dev.yml"
DEFAULT_RETRY_INTERVAL=5
DEFAULT_MAX_RETRIES=60

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Test tracking
TESTS_TOTAL=0
TESTS_PASSED=0
TESTS_FAILED=0
START_TIME=$(date +%s)

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Print colored output
print_header() {
    echo -e "${BLUE}=============================================================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}=============================================================================${NC}"
}

print_section() {
    echo -e "${CYAN}=== $1 ===${NC}"
}

print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    ((TESTS_PASSED++))
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    ((TESTS_FAILED++))
}

print_debug() {
    if [[ "${VERBOSE:-false}" == "true" ]]; then
        echo -e "${PURPLE}[DEBUG]${NC} $1"
    fi
}

# Increment test counter
inc_test() {
    ((TESTS_TOTAL++))
}

# Wait for service to be healthy
wait_for_service() {
    local service_name="$1"
    local timeout="${2:-$DEFAULT_TIMEOUT}"
    local retries=0
    local max_retries=$((timeout / DEFAULT_RETRY_INTERVAL))
    
    print_info "Waiting for service '$service_name' to be healthy (timeout: ${timeout}s)..."
    
    while [[ $retries -lt $max_retries ]]; do
        if docker-compose -f "$COMPOSE_FILE" ps -q "$service_name" > /dev/null 2>&1; then
            local health_status
            health_status=$(docker-compose -f "$COMPOSE_FILE" ps --format "table {{.Service}}\t{{.State}}\t{{.Health}}" | grep "^$service_name" | awk '{print $3}' || echo "unknown")
            
            print_debug "Service '$service_name' health status: $health_status"
            
            if [[ "$health_status" == "healthy" ]]; then
                print_success "Service '$service_name' is healthy"
                return 0
            elif [[ "$health_status" == "unhealthy" ]]; then
                print_error "Service '$service_name' is unhealthy"
                return 1
            fi
        else
            print_debug "Service '$service_name' not found or not running"
        fi
        
        sleep $DEFAULT_RETRY_INTERVAL
        ((retries++))
        
        if [[ $((retries % 6)) -eq 0 ]]; then
            print_info "Still waiting for '$service_name'... (${retries}/${max_retries} attempts)"
        fi
    done
    
    print_error "Service '$service_name' failed to become healthy within ${timeout}s"
    return 1
}

# Test HTTP endpoint
test_http_endpoint() {
    local name="$1"
    local url="$2"
    local expected_status="${3:-200}"
    local timeout="${4:-10}"
    
    inc_test
    print_debug "Testing HTTP endpoint: $name -> $url"
    
    local response_code
    response_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$timeout" "$url" 2>/dev/null || echo "000")
    
    if [[ "$response_code" == "$expected_status" ]]; then
        print_success "HTTP endpoint '$name' returned $response_code"
        return 0
    else
        print_error "HTTP endpoint '$name' returned $response_code (expected $expected_status)"
        return 1
    fi
}

# Test service version
test_service_version() {
    local service_name="$1"
    local version_command="$2"
    local expected_pattern="${3:-.*}"
    
    inc_test
    print_debug "Testing service version: $service_name"
    
    local version_output
    if version_output=$(docker-compose -f "$COMPOSE_FILE" exec -T "$service_name" $version_command 2>/dev/null); then
        if echo "$version_output" | grep -qE "$expected_pattern"; then
            print_success "Service '$service_name' version check passed: $(echo "$version_output" | head -1 | cut -c1-50)..."
            return 0
        else
            print_error "Service '$service_name' version check failed: unexpected output"
            print_debug "Output: $version_output"
            return 1
        fi
    else
        print_error "Service '$service_name' version check failed: command execution failed"
        return 1
    fi
}

# Test database connectivity
test_database_connectivity() {
    local service_name="$1"
    local database="${2:-freecad}"
    local user="${3:-freecad}"
    
    inc_test
    print_debug "Testing database connectivity: $service_name"
    
    local query="SELECT version();"
    if docker-compose -f "$COMPOSE_FILE" exec -T "$service_name" psql -U "$user" -d "$database" -c "$query" > /dev/null 2>&1; then
        print_success "Database '$service_name' connectivity test passed"
        return 0
    else
        print_error "Database '$service_name' connectivity test failed"
        return 1
    fi
}

# Test Redis connectivity
test_redis_connectivity() {
    local service_name="$1"
    
    inc_test
    print_debug "Testing Redis connectivity: $service_name"
    
    if docker-compose -f "$COMPOSE_FILE" exec -T "$service_name" redis-cli ping | grep -q "PONG"; then
        print_success "Redis '$service_name' connectivity test passed"
        return 0
    else
        print_error "Redis '$service_name' connectivity test failed"
        return 1
    fi
}

# Test RabbitMQ connectivity
test_rabbitmq_connectivity() {
    local service_name="$1"
    
    inc_test
    print_debug "Testing RabbitMQ connectivity: $service_name"
    
    if docker-compose -f "$COMPOSE_FILE" exec -T "$service_name" rabbitmq-diagnostics -q ping > /dev/null 2>&1; then
        print_success "RabbitMQ '$service_name' connectivity test passed"
        return 0
    else
        print_error "RabbitMQ '$service_name' connectivity test failed"
        return 1
    fi
}

# Test MinIO connectivity
test_minio_connectivity() {
    local service_name="$1"
    
    inc_test
    print_debug "Testing MinIO connectivity: $service_name"
    
    # Test MinIO health endpoint
    if test_http_endpoint "MinIO Health" "http://localhost:9000/minio/health/live" "200" "10"; then
        print_success "MinIO '$service_name' connectivity test passed"
        return 0
    else
        print_error "MinIO '$service_name' connectivity test failed"
        return 1
    fi
}

# =============================================================================
# ARGUMENT PARSING
# =============================================================================

TIMEOUT=$DEFAULT_TIMEOUT
COMPOSE_FILE=$DEFAULT_COMPOSE_FILE
VERBOSE=false
SKIP_UTILITIES=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --timeout=*)
            TIMEOUT="${1#*=}"
            shift
            ;;
        --compose-file=*)
            COMPOSE_FILE="${1#*=}"
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        --skip-utilities)
            SKIP_UTILITIES=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --timeout=SECONDS        Maximum wait time for services (default: $DEFAULT_TIMEOUT)"
            echo "  --compose-file=PATH      Path to docker-compose file (default: $DEFAULT_COMPOSE_FILE)"
            echo "  --verbose                Enable verbose output"
            echo "  --skip-utilities         Skip utility services tests"
            echo "  --help, -h               Show this help message"
            echo ""
            echo "Examples:"
            echo "  $0                                           # Run with defaults"
            echo "  $0 --timeout=600 --verbose                  # Longer timeout with verbose output"
            echo "  $0 --skip-utilities                         # Skip utility services"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information."
            exit 1
            ;;
    esac
done

# =============================================================================
# MAIN EXECUTION
# =============================================================================

main() {
    print_header "$SCRIPT_NAME v$SCRIPT_VERSION"
    
    print_info "Configuration:"
    print_info "  Compose file: $COMPOSE_FILE"
    print_info "  Timeout: ${TIMEOUT}s"
    print_info "  Verbose: $VERBOSE"
    print_info "  Skip utilities: $SKIP_UTILITIES"
    echo ""
    
    # Verify compose file exists
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        print_error "Docker Compose file not found: $COMPOSE_FILE"
        exit 1
    fi
    
    # Verify docker-compose is available
    if ! command -v docker-compose &> /dev/null; then
        print_error "docker-compose command not found. Please install Docker Compose."
        exit 1
    fi
    
    # =============================================================================
    # SERVICE HEALTH CHECKS
    # =============================================================================
    
    print_section "Service Health Checks"
    
    # Core database services
    print_info "Testing core database services..."
    wait_for_service "postgres" "$TIMEOUT" || exit 1
    wait_for_service "redis" "$TIMEOUT" || exit 1
    
    # Message broker
    print_info "Testing message broker..."
    wait_for_service "rabbitmq" "$TIMEOUT" || exit 1
    
    # Object storage
    print_info "Testing object storage..."
    wait_for_service "minio" "$TIMEOUT" || exit 1
    
    # Application services
    print_info "Testing application services..."
    wait_for_service "api" "$TIMEOUT" || exit 1
    wait_for_service "workers" "$TIMEOUT" || exit 1
    wait_for_service "beat" "$TIMEOUT" || exit 1
    wait_for_service "web" "$TIMEOUT" || exit 1
    
    # Utility services (if not skipped)
    if [[ "$SKIP_UTILITIES" != "true" ]]; then
        print_info "Testing utility services..."
        wait_for_service "freecad" "$TIMEOUT" || print_warning "FreeCAD service not healthy (continuing...)"
        wait_for_service "camotics" "$TIMEOUT" || print_warning "CAMotics service not healthy (continuing...)"
        wait_for_service "ffmpeg" "$TIMEOUT" || print_warning "FFmpeg service not healthy (continuing...)"
        # ClamAV is optional (profile-based)
        if docker-compose -f "$COMPOSE_FILE" ps -q clamav > /dev/null 2>&1; then
            wait_for_service "clamav" "$TIMEOUT" || print_warning "ClamAV service not healthy (continuing...)"
        fi
    fi
    
    echo ""
    
    # =============================================================================
    # CONNECTIVITY TESTS
    # =============================================================================
    
    print_section "Service Connectivity Tests"
    
    # Database connectivity
    print_info "Testing database connectivity..."
    test_database_connectivity "postgres" "freecad" "freecad"
    
    # Cache connectivity
    print_info "Testing cache connectivity..."
    test_redis_connectivity "redis"
    
    # Message broker connectivity
    print_info "Testing message broker connectivity..."
    test_rabbitmq_connectivity "rabbitmq"
    
    # Object storage connectivity
    print_info "Testing object storage connectivity..."
    test_minio_connectivity "minio"
    
    echo ""
    
    # =============================================================================
    # HTTP ENDPOINT TESTS
    # =============================================================================
    
    print_section "HTTP Endpoint Tests"
    
    # API endpoints
    print_info "Testing API endpoints..."
    test_http_endpoint "API Health Check" "http://localhost:8000/api/v1/healthz" "200"
    test_http_endpoint "API Root" "http://localhost:8000/" "200"
    test_http_endpoint "API OpenAPI Docs" "http://localhost:8000/docs" "200"
    
    # Web application endpoints
    print_info "Testing web application endpoints..."
    test_http_endpoint "Web Health Check" "http://localhost:3000/healthz" "200"
    test_http_endpoint "Web Root" "http://localhost:3000/" "200"
    
    # MinIO management endpoints
    print_info "Testing MinIO endpoints..."
    test_http_endpoint "MinIO API Health" "http://localhost:9000/minio/health/live" "200"
    test_http_endpoint "MinIO Console" "http://localhost:9001/" "200"
    
    # RabbitMQ management
    print_info "Testing RabbitMQ management..."
    test_http_endpoint "RabbitMQ Management" "http://localhost:15672/" "200"
    
    echo ""
    
    # =============================================================================
    # VERSION CHECKS
    # =============================================================================
    
    print_section "Service Version Checks"
    
    # Database versions
    print_info "Testing database versions..."
    test_service_version "postgres" "psql --version" "PostgreSQL"
    test_service_version "redis" "redis-server --version" "Redis server"
    
    # Message broker version
    print_info "Testing message broker version..."
    test_service_version "rabbitmq" "rabbitmq-diagnostics status" "RabbitMQ"
    
    # Application service versions
    print_info "Testing application service versions..."
    test_service_version "api" "python --version" "Python"
    test_service_version "web" "node --version" "v"
    
    # Utility service versions (if not skipped)
    if [[ "$SKIP_UTILITIES" != "true" ]]; then
        print_info "Testing utility service versions..."
        test_service_version "freecad" "freecadcmd --version" "FreeCAD" || print_warning "FreeCAD version check failed (continuing...)"
        test_service_version "camotics" "camotics --version" "CAMotics" || print_warning "CAMotics version check failed (continuing...)"
        test_service_version "ffmpeg" "ffmpeg -version" "ffmpeg version" || print_warning "FFmpeg version check failed (continuing...)"
        
        # ClamAV version (if running)
        if docker-compose -f "$COMPOSE_FILE" ps -q clamav > /dev/null 2>&1; then
            test_service_version "clamav" "clamscan --version" "ClamAV" || print_warning "ClamAV version check failed (continuing...)"
        fi
    fi
    
    echo ""
    
    # =============================================================================
    # FUNCTIONAL TESTS
    # =============================================================================
    
    print_section "Functional Tests"
    
    # Test MinIO bucket creation
    inc_test
    print_info "Testing MinIO bucket functionality..."
    if docker-compose -f "$COMPOSE_FILE" logs minio-bootstrap 2>/dev/null | grep -q "Bootstrap complete"; then
        print_success "MinIO bucket creation completed successfully"
    else
        print_error "MinIO bucket creation failed or incomplete"
    fi
    
    # Test Celery worker functionality
    inc_test
    print_info "Testing Celery worker functionality..."
    if docker-compose -f "$COMPOSE_FILE" exec -T workers celery -A app.tasks.worker inspect stats > /dev/null 2>&1; then
        print_success "Celery workers are responding to inspect commands"
    else
        print_error "Celery workers failed to respond to inspect commands"
    fi
    
    # Test Celery beat functionality
    inc_test
    print_info "Testing Celery beat functionality..."
    if docker-compose -f "$COMPOSE_FILE" logs beat 2>/dev/null | grep -q "beat" || \
       docker-compose -f "$COMPOSE_FILE" exec -T beat pgrep -f "celery.*beat" > /dev/null 2>&1; then
        print_success "Celery beat scheduler is running"
    else
        print_error "Celery beat scheduler is not running properly"
    fi
    
    echo ""
    
    # =============================================================================
    # RESULTS SUMMARY
    # =============================================================================
    
    print_section "Test Results Summary"
    
    local end_time=$(date +%s)
    local duration=$((end_time - START_TIME))
    
    echo ""
    print_info "Execution Summary:"
    print_info "  Total Tests: $TESTS_TOTAL"
    print_info "  Passed: $TESTS_PASSED"
    print_info "  Failed: $TESTS_FAILED"
    print_info "  Duration: ${duration}s"
    
    if [[ $TESTS_FAILED -eq 0 ]]; then
        echo ""
        print_header "🎉 ALL SMOKE TESTS PASSED! 🎉"
        print_success "FreeCAD Platform development environment is ready for use."
        
        echo ""
        print_info "Services available at:"
        print_info "  • Web Application:     http://localhost:3000"
        print_info "  • API Documentation:   http://localhost:8000/docs"
        print_info "  • MinIO Console:       http://localhost:9001"
        print_info "  • RabbitMQ Management: http://localhost:15672"
        print_info "  • Database:            localhost:5432"
        print_info "  • Redis:               localhost:6379"
        
        exit 0
    else
        echo ""
        print_header "❌ SMOKE TESTS FAILED ❌"
        print_error "Some tests failed. Please check the output above and fix issues before using the environment."
        
        echo ""
        print_info "Troubleshooting tips:"
        print_info "  • Check service logs: docker-compose -f $COMPOSE_FILE logs [service_name]"
        print_info "  • Restart services: docker-compose -f $COMPOSE_FILE restart [service_name]"
        print_info "  • Check service status: docker-compose -f $COMPOSE_FILE ps"
        print_info "  • Rebuild services: docker-compose -f $COMPOSE_FILE up -d --build"
        
        exit 1
    fi
}

# Trap to ensure cleanup on script exit
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        print_error "Script interrupted or failed. Exit code: $exit_code"
    fi
    exit $exit_code
}

trap cleanup INT TERM EXIT

# Run main function
main "$@"