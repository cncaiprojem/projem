#!/bin/bash
# Script to generate golden artefacts using the FreeCAD container
# This ensures FreeCAD is available for the generation process

set -e
set -o pipefail

# Color output for better visibility
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're running in Docker Compose environment
if [ -z "$DOCKER_COMPOSE_FILE" ]; then
    DOCKER_COMPOSE_FILE="infra/compose/docker-compose.test.yml"
fi

# Function to run golden generation in the FreeCAD container
generate_golden() {
    log_info "Starting golden artefact generation in FreeCAD container"

    # Build the command to run in the FreeCAD container
    GENERATE_CMD="cd /app && python tools/gen_golden.py --regenerate"

    # Check if additional arguments were provided
    if [ $# -gt 0 ]; then
        GENERATE_CMD="$GENERATE_CMD $*"
    fi

    # Run the generation in the FreeCAD container
    log_info "Running: docker compose -f $DOCKER_COMPOSE_FILE exec freecad_test bash -c \"$GENERATE_CMD\""

    docker compose -f "$DOCKER_COMPOSE_FILE" exec freecad_test bash -c "$GENERATE_CMD"

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
        log_info "Golden artefact generation completed successfully!"

        # Verify the generated artefacts
        log_info "Verifying generated artefacts..."
        docker compose -f "$DOCKER_COMPOSE_FILE" exec freecad_test bash -c "cd /app && python tools/gen_golden.py --verify"

        VERIFY_CODE=$?
        if [ $VERIFY_CODE -eq 0 ]; then
            log_info "Verification successful!"
        else
            log_warning "Verification failed with exit code: $VERIFY_CODE"
        fi
    else
        log_error "Golden generation failed with exit code: $EXIT_CODE"
        exit $EXIT_CODE
    fi
}

# Main execution
main() {
    # Check if services are running
    log_info "Checking if test services are running..."

    if ! docker compose -f "$DOCKER_COMPOSE_FILE" ps freecad_test | grep -q "Up"; then
        log_warning "FreeCAD test container is not running. Starting services..."
        docker compose -f "$DOCKER_COMPOSE_FILE" up -d freecad_test postgres_test redis_test minio_test rabbitmq_test

        # Wait for services to be ready
        log_info "Waiting for services to be ready..."
        sleep 10
    fi

    # Generate golden artefacts
    generate_golden "$@"
}

# Run main function with all arguments
main "$@"