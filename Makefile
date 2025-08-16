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

.PHONY: help init dev dev-full stop logs migrate seed test lint fmt build clean gen-docs run-freecad-smoke run-s3-smoke seed-basics pre-commit-install pre-commit-run pre-commit-check rabbitmq-setup rabbitmq-status dlq-status rabbitmq-ui test-celery-rabbitmq

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
