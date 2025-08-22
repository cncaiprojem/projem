#!/bin/bash

# Task 6.1: RabbitMQ Topology Initialization Script
# Runs the Python-based queue topology setup for the new DLX/DLQ structure

set -e

# Renk kodları
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Script dizinini bul
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

log_info "=== Task 6.1: RabbitMQ Topology Kurulumu ==="
log_info "Project Root: $PROJECT_ROOT"

# Python initialization script'inin yerini kontrol et
INIT_SCRIPT="$PROJECT_ROOT/infra/rabbitmq/init_queues.py"

if [ ! -f "$INIT_SCRIPT" ]; then
    log_error "Python initialization script bulunamadı: $INIT_SCRIPT"
    exit 1
fi

log_info "Python initialization script bulundu: $INIT_SCRIPT"

# RabbitMQ environment variables
export RABBITMQ_HOST="${RABBITMQ_HOST:-localhost}"
export RABBITMQ_MGMT_PORT="${RABBITMQ_MGMT_PORT:-15672}"
export RABBITMQ_USER="${RABBITMQ_USER:-freecad}"
export RABBITMQ_PASS="${RABBITMQ_PASS:-freecad}"
export RABBITMQ_VHOST="${RABBITMQ_VHOST:-/}"

log_info "RabbitMQ ayarları:"
log_info "  Host: $RABBITMQ_HOST:$RABBITMQ_MGMT_PORT"
log_info "  User: $RABBITMQ_USER"
log_info "  VHost: $RABBITMQ_VHOST"

# Python script'ini çalıştır
log_info "Python topology initialization script çalıştırılıyor..."

if command -v python3 >/dev/null 2>&1; then
    PYTHON_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_CMD="python"
else
    log_error "Python bulunamadı! Python 3 yüklü olmalı."
    exit 1
fi

log_info "Python komutu: $PYTHON_CMD"

# Dependencies kontrolü
log_info "Python dependencies kontrol ediliyor..."
$PYTHON_CMD -c "import requests; print('requests OK')" || {
    log_error "Python 'requests' modülü bulunamadı!"
    log_error "Yüklemek için: pip install requests"
    exit 1
}

# Script'i çalıştır
cd "$PROJECT_ROOT"
$PYTHON_CMD "$INIT_SCRIPT"

if [ $? -eq 0 ]; then
    log_info "✅ Task 6.1 topology kurulumu başarıyla tamamlandı!"
    
    log_info ""
    log_info "📋 Sonraki adımlar:"
    log_info "1. Test script'ini çalıştırın:"
    log_info "   python apps/api/app/scripts/test_dlx_dlq_topology.py"
    log_info "2. Celery worker'larını yeni queue'larla başlatın:"
    log_info "   docker-compose -f infra/compose/docker-compose.dev.yml up workers workers-priority"
    log_info "3. RabbitMQ Management UI'da kontrol edin:"
    log_info "   http://$RABBITMQ_HOST:$RABBITMQ_MGMT_PORT"
    log_info ""
    
else
    log_error "❌ Task 6.1 topology kurulumu BAŞARISIZ!"
    exit 1
fi