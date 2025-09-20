# Cross-platform Makefile (Windows cmd.exe / Unix bash) for CNC/CAM/CAD project
# Usage:
#   make init   -> copy .env.example to .env
#   make dev    -> start full stack (docker compose up --build)
#   make stop   -> stop stack
#   make logs   -> tail all logs
#   make migrate/seed/test/lint/fmt/build/clean/gen-docs

# --- Shell & tools selection ---
ifeq ($(OS),Windows_NT)
  SHELL := cmd.exe
  .SHELLFLAGS := /V:ON /c
  COPY := copy /Y
  RM := del /Q
else
  SHELL := /bin/bash
  .SHELLFLAGS := -euo pipefail -c
  COPY := cp -f
  RM := rm -f
endif

DC ?= docker compose -f infra/compose/docker-compose.dev.yml

.DEFAULT_GOAL := help

.PHONY: help init dev dev-full stop logs migrate seed test lint fmt build clean gen-docs run-freecad-smoke run-s3-smoke seed-basics pre-commit-install pre-commit-run pre-commit-check rabbitmq-setup rabbitmq-status dlq-status rabbitmq-ui test-celery-rabbitmq test-migration-integrity test-migration-safety test-constraints test-audit-integrity test-performance test-turkish-compliance test-golden gen-golden verify-golden test-integration-ci

help:
	@echo.
	@echo Available targets:
	@echo   make init      - Create .env from .env.example
	@echo   make dev       - Start development stack with all services
	@echo   make dev-full  - Start development stack with all services (same as dev)
	@echo   make stop      - Stop stack (docker compose down)
	@echo   make logs      - Follow logs from all services
	@echo   make migrate   - Run Alembic migrations
	@echo   make seed      - Seed example data
	@echo   make test      - Run API and Web tests
	@echo   make lint      - Run linters (API + Web)
	@echo   make fmt       - Auto-format code (API + Web)
	@echo   make build     - Build docker images
	@echo   make clean     - Down and remove volumes
	@echo   make gen-docs  - Generate API/docs (if script exists)
	@echo.
	@echo Smoke Tests:
	@echo   make run-freecad-smoke - Test FreeCAD functionality
	@echo   make run-s3-smoke      - Test S3/MinIO functionality
	@echo.
	@echo Golden Artefacts (Task 7.14):
	@echo   make test-golden       - Run golden artefact tests in test environment
	@echo   make gen-golden        - Generate golden artefacts with FreeCAD
	@echo   make verify-golden     - Verify golden artefacts against manifests
	@echo   make test-integration-ci - Run full CI integration test suite
	@echo   make test-unit-ci      - Run unit tests in CI environment
	@echo   make test-performance-ci - Run performance tests in CI environment
	@echo   make test-clean        - Clean up test environment and artefacts
	@echo.
	@echo RabbitMQ Management:
	@echo   make rabbitmq-setup   - Initialize RabbitMQ queues and DLX
	@echo   make rabbitmq-status  - Show RabbitMQ cluster status
	@echo   make dlq-status       - Show Dead Letter Queue status
	@echo   make rabbitmq-ui      - Open RabbitMQ Management UI
	@echo   make test-celery-rabbitmq - Test Celery RabbitMQ configuration
	@echo.
	@echo Pre-commit hooks:
	@echo   make pre-commit-install - Install pre-commit hooks
	@echo   make pre-commit-run     - Run pre-commit on all files
	@echo   make pre-commit-check   - Check pre-commit configuration
	@echo.
	@echo Migration and Integrity Tests (Task 2.9):
	@echo   make test-migration-integrity - Run complete migration integrity test suite
	@echo   make test-migration-safety    - Run migration upgrade/downgrade safety tests
	@echo   make test-constraints         - Run database constraint validation tests
	@echo   make test-audit-integrity     - Run audit chain cryptographic integrity tests
	@echo   make test-performance         - Run query performance and index usage tests
	@echo   make test-turkish-compliance  - Run Turkish KVKV/GDPR compliance tests
	@echo.

init:
	$(COPY) .env.example .env

dev:
	$(DC) up --build

dev-full:
	$(DC) up --build

stop:
	$(DC) down

logs:
	$(DC) logs -f

migrate:
	$(DC) exec api alembic upgrade head

seed:
	-$(DC) exec api python -m app.scripts.seed

seed-basics:
	-$(DC) exec api python -m app.scripts.seed_basics

test:
	-$(DC) exec api pytest -q
	-$(DC) exec web pnpm test

lint:
	-$(DC) exec api ruff check .
	-$(DC) exec api black --check .
	-$(DC) exec web pnpm lint

fmt:
	-$(DC) exec api ruff format
	-$(DC) exec api black .
	-$(DC) exec web pnpm format

build:
	$(DC) build

run-freecad-smoke:
	-$(DC) exec api python -m app.scripts.run_freecad_smoke

run-s3-smoke:
	-$(DC) exec api python -m app.scripts.test_s3_functionality

clean:
	$(DC) down -v

gen-docs:
	-$(DC) exec api python -m app.scripts.gen_docs

# RabbitMQ yönetim komutları
# RabbitMQ queue'ları ve DLX konfigürasyonunu başlat
rabbitmq-setup:
	@echo RabbitMQ DLX konfigürasyonu başlatılıyor...
	$(DC) exec rabbitmq /opt/rabbitmq/init-rabbitmq.sh setup

# RabbitMQ cluster durumunu kontrol et
rabbitmq-status:
	@echo RabbitMQ cluster durumu:
	-$(DC) exec rabbitmq rabbitmq-diagnostics status
	@echo.
	@echo Queue durumu:
	-$(DC) exec rabbitmq /opt/rabbitmq/init-rabbitmq.sh status

# Dead Letter Queue durumunu kontrol et
dlq-status:
	@echo Dead Letter Queue durumu:
	-$(DC) exec rabbitmq /opt/rabbitmq/init-rabbitmq.sh dlq-status

# RabbitMQ Management UI'yi aç
rabbitmq-ui:
ifeq ($(OS),Windows_NT)
	@echo RabbitMQ Management UI açılıyor...
	@echo URL: http://localhost:15672
	@echo Username: freecad
	@echo Password: freecad
	@start http://localhost:15672
else
	@echo "RabbitMQ Management UI: http://localhost:15672"
	@echo "Username: freecad, Password: freecad"
	@which xdg-open >/dev/null 2>&1 && xdg-open http://localhost:15672 || echo "xdg-open not found, open manually"
endif

# Pre-commit hooks yönetimi
# Kod kalitesi ve standartları için otomatik kontroller

pre-commit-install:
	@echo Installing pre-commit hooks...
ifeq ($(OS),Windows_NT)
	@echo Checking if pre-commit is installed...
	@pre-commit --version 2>nul || (echo ERROR: pre-commit not found. Install with: pip install pre-commit && exit /b 1)
	@echo Installing pre-commit hooks to .git/hooks/...
	@pre-commit install
	@pre-commit install --hook-type commit-msg
	@echo Pre-commit hooks installed successfully!
	@echo.
	@echo Usage:
	@echo   - Hooks will run automatically on git commit
	@echo   - To run manually: make pre-commit-run
	@echo   - To skip hooks: git commit --no-verify
else
	@command -v pre-commit >/dev/null 2>&1 || { echo "ERROR: pre-commit not found. Install with: pip install pre-commit"; exit 1; }
	@echo "Installing pre-commit hooks to .git/hooks/..."
	@pre-commit install
	@pre-commit install --hook-type commit-msg
	@echo "Pre-commit hooks installed successfully!"
	@echo ""
	@echo "Usage:"
	@echo "  - Hooks will run automatically on git commit"
	@echo "  - To run manually: make pre-commit-run"
	@echo "  - To skip hooks: git commit --no-verify"
endif

pre-commit-run:
	@echo Running pre-commit hooks on all files...
ifeq ($(OS),Windows_NT)
	@pre-commit --version 2>nul || (echo ERROR: pre-commit not found. Install with: pip install pre-commit && exit /b 1)
	@pre-commit run --all-files
else
	@command -v pre-commit >/dev/null 2>&1 || { echo "ERROR: pre-commit not found. Install with: pip install pre-commit"; exit 1; }
	@pre-commit run --all-files
endif

pre-commit-check:
	@echo Checking pre-commit configuration...
ifeq ($(OS),Windows_NT)
	@pre-commit --version 2>nul || (echo ERROR: pre-commit not found. Install with: pip install pre-commit && exit /b 1)
	@echo Validating .pre-commit-config.yaml...
	@pre-commit validate-config
	@echo Configuration is valid!
	@echo.
	@echo Checking hook installation status...
	@if exist .git\hooks\pre-commit (echo ✓ Pre-commit hook is installed) else (echo ✗ Pre-commit hook is NOT installed - run: make pre-commit-install)
else
	@command -v pre-commit >/dev/null 2>&1 || { echo "ERROR: pre-commit not found. Install with: pip install pre-commit"; exit 1; }
	@echo "Validating .pre-commit-config.yaml..."
	@pre-commit validate-config
	@echo "Configuration is valid!"
	@echo ""
	@echo "Checking hook installation status..."
	@if [ -f .git/hooks/pre-commit ]; then echo "✓ Pre-commit hook is installed"; else echo "✗ Pre-commit hook is NOT installed - run: make pre-commit-install"; fi
endif

# Celery RabbitMQ konfigürasyon testi
test-celery-rabbitmq:
	@echo Testing Celery RabbitMQ configuration...
	$(DC) exec api python -m app.scripts.test_celery_rabbitmq

# Migration and Integrity Tests (Task 2.9) - Banking-Level Precision
# Comprehensive test suite for migration safety, database integrity,
# audit chain security, and performance validation

test-migration-integrity:
	@echo Running complete migration integrity test suite (Task 2.9)...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --suite all --verbose --report --safety-check

test-migration-safety:
	@echo Running migration upgrade/downgrade safety tests...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --suite migration --verbose --safety-check

test-constraints:
	@echo Running database constraint validation tests...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --suite constraints --verbose

test-audit-integrity:
	@echo Running audit chain cryptographic integrity tests...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --suite audit --verbose

test-performance:
	@echo Running query performance and index usage tests...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --suite performance --verbose --performance

test-turkish-compliance:
	@echo Running Turkish KVKV/GDPR compliance tests...
	$(DC) exec api python scripts/run_migration_integrity_tests.py --compliance --verbose

# Task 7.14: Golden Artefacts and Integration Testing
# Define test compose file
DC_TEST := docker compose -f infra/compose/docker-compose.test.yml

test-golden:
	@echo Running golden artefact integration tests in test environment...
	$(DC_TEST) up -d postgres_test redis_test minio_test rabbitmq_test freecad_test
	$(DC_TEST) run --rm test_runner

gen-golden:
	@echo Generating golden artefacts with FreeCAD...
	$(DC_TEST) up -d postgres_test redis_test minio_test freecad_test
	$(DC_TEST) run --rm --profile golden golden_generator

verify-golden:
	@echo Verifying golden artefacts...
	$(DC_TEST) up -d freecad_test
	$(DC_TEST) exec freecad_test bash -c "cd /app && python tools/gen_golden.py --verify"

test-integration-ci:
	@echo Running full CI integration test suite...
	$(DC_TEST) up -d
	TEST_TYPE=all $(DC_TEST) run --rm test_runner
	$(DC_TEST) down -v

# Additional test targets for different test types
test-unit-ci:
	@echo Running unit tests in CI environment...
	TEST_TYPE=unit $(DC_TEST) run --rm test_runner

test-performance-ci:
	@echo Running performance tests in CI environment...
	TEST_TYPE=performance $(DC_TEST) run --rm test_runner

# Clean up test environment
test-clean:
	@echo Cleaning up test environment...
	$(DC_TEST) down -v
	rm -rf infra/compose/test_artefacts
	rm -rf infra/compose/golden_artefacts
