#!/bin/bash

# RabbitMQ İlk Kurulum ve DLX Konfigürasyonu
# Bu script RabbitMQ başlatıldıktan sonra çalışır ve queue'ları, exchange'leri ve DLX'leri kurar
# Türkçe: RabbitMQ Dead Letter Exchange (DLX) ve queue yapılandırması

set -e

# Renk kodları için
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

# RabbitMQ bağlantı ayarları
RABBITMQ_HOST="${RABBITMQ_HOST:-localhost}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"
RABBITMQ_MGMT_PORT="${RABBITMQ_MGMT_PORT:-15672}"
RABBITMQ_USER="${RABBITMQ_USER:-freecad}"
RABBITMQ_PASS="${RABBITMQ_PASS:-freecad}"
RABBITMQ_VHOST="${RABBITMQ_VHOST:-/}"

# Management API endpoint
MGMT_API="http://${RABBITMQ_HOST}:${RABBITMQ_MGMT_PORT}/api"

log_info "RabbitMQ DLX Konfigürasyonu başlatılıyor..."
log_debug "Host: ${RABBITMQ_HOST}:${RABBITMQ_PORT}"
log_debug "Management: ${RABBITMQ_HOST}:${RABBITMQ_MGMT_PORT}"
log_debug "User: ${RABBITMQ_USER}"
log_debug "VHost: ${RABBITMQ_VHOST}"

# RabbitMQ'nun hazır olmasını bekle
wait_for_rabbitmq() {
    log_info "RabbitMQ servisinin hazır olması bekleniyor..."
    local max_attempts=30
    local attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
               -s -f "${MGMT_API}/aliveness-test/${RABBITMQ_VHOST//\//%2F}" > /dev/null 2>&1; then
            log_info "RabbitMQ hazır! (Deneme: $attempt/$max_attempts)"
            return 0
        fi
        
        log_warn "RabbitMQ henüz hazır değil, bekleniyor... (Deneme: $attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done
    
    log_error "RabbitMQ $max_attempts deneme sonrası hazır değil!"
    return 1
}

# Exchange tanımla
declare_exchange() {
    local name=$1
    local type=$2
    local durable=${3:-true}
    
    log_info "Exchange tanımlanıyor: $name (type: $type)"
    
    curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
         -X PUT \
         -H "Content-Type: application/json" \
         -d "{\"type\":\"$type\",\"durable\":$durable}" \
         "${MGMT_API}/exchanges/${RABBITMQ_VHOST//\//%2F}/$name" \
         -s -f > /dev/null
    
    if [ $? -eq 0 ]; then
        log_info "✓ Exchange '$name' başarıyla oluşturuldu"
    else
        log_error "✗ Exchange '$name' oluşturulamadı"
        return 1
    fi
}

# Queue tanımla
declare_queue() {
    local name=$1
    local durable=${2:-true}
    local dlx_exchange=${3:-""}
    local dlx_routing_key=${4:-""}
    local message_ttl=${5:-""}
    local max_retries=${6:-3}
    
    log_info "Queue tanımlanıyor: $name"
    
    local arguments="{\"durable\":$durable"
    
    # DLX ayarları
    if [ -n "$dlx_exchange" ]; then
        arguments+=",\"arguments\":{\"x-dead-letter-exchange\":\"$dlx_exchange\""
        if [ -n "$dlx_routing_key" ]; then
            arguments+=",\"x-dead-letter-routing-key\":\"$dlx_routing_key\""
        fi
        if [ -n "$message_ttl" ]; then
            arguments+=",\"x-message-ttl\":$message_ttl"
        fi
        # x-max-retries is not used - retries handled by Celery
        arguments+="}}"
    else
        arguments+="}"
    fi
    
    log_debug "Queue arguments: $arguments"
    
    curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
         -X PUT \
         -H "Content-Type: application/json" \
         -d "$arguments" \
         "${MGMT_API}/queues/${RABBITMQ_VHOST//\//%2F}/$name" \
         -s -f > /dev/null
    
    if [ $? -eq 0 ]; then
        log_info "✓ Queue '$name' başarıyla oluşturuldu"
    else
        log_error "✗ Queue '$name' oluşturulamadı"
        return 1
    fi
}

# Binding oluştur
create_binding() {
    local source=$1
    local destination=$2
    local routing_key=${3:-""}
    local dest_type=${4:-"queue"}
    
    log_info "Binding oluşturuluyor: $source -> $destination"
    
    local binding_data="{\"routing_key\":\"$routing_key\"}"
    
    curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
         -X POST \
         -H "Content-Type: application/json" \
         -d "$binding_data" \
         "${MGMT_API}/bindings/${RABBITMQ_VHOST//\//%2F}/e/$source/$dest_type/$destination" \
         -s -f > /dev/null
    
    if [ $? -eq 0 ]; then
        log_info "✓ Binding '$source -> $destination' başarıyla oluşturuldu"
    else
        log_error "✗ Binding '$source -> $destination' oluşturulamadı"
        return 1
    fi
}

# User permissions ayarla
set_permissions() {
    local username=$1
    local configure=${2:-".*"}
    local write=${3:-".*"}
    local read=${4:-".*"}
    
    log_info "User permissions ayarlanıyor: $username"
    
    local permissions="{\"configure\":\"$configure\",\"write\":\"$write\",\"read\":\"$read\"}"
    
    curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
         -X PUT \
         -H "Content-Type: application/json" \
         -d "$permissions" \
         "${MGMT_API}/permissions/${RABBITMQ_VHOST//\//%2F}/$username" \
         -s -f > /dev/null
    
    if [ $? -eq 0 ]; then
        log_info "✓ User '$username' permissions başarıyla ayarlandı"
    else
        log_error "✗ User '$username' permissions ayarlanamadı"
        return 1
    fi
}

# Policy tanımla
declare_policy() {
    local name=$1
    local pattern=$2
    local definition=$3
    local priority=${4:-0}
    local apply_to=${5:-"queues"}
    
    log_info "Policy tanımlanıyor: $name"
    
    local policy_data="{\"pattern\":\"$pattern\",\"definition\":$definition,\"priority\":$priority,\"apply-to\":\"$apply_to\"}"
    
    curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
         -X PUT \
         -H "Content-Type: application/json" \
         -d "$policy_data" \
         "${MGMT_API}/policies/${RABBITMQ_VHOST//\//%2F}/$name" \
         -s -f > /dev/null
    
    if [ $? -eq 0 ]; then
        log_info "✓ Policy '$name' başarıyla oluşturuldu"
    else
        log_error "✗ Policy '$name' oluşturulamadı"
        return 1
    fi
}

# Ana konfigürasyon fonksiyonu
setup_rabbitmq() {
    log_info "=== RabbitMQ Dead Letter Exchange Konfigürasyonu ==="
    
    # RabbitMQ'nun hazır olmasını bekle
    if ! wait_for_rabbitmq; then
        log_error "RabbitMQ başlatılamadı, konfigürasyon durduruldu"
        exit 1
    fi
    
    # 1. Dead Letter Exchange'leri oluştur
    log_info "--- Dead Letter Exchange'ler oluşturuluyor ---"
    declare_exchange "dlx" "direct" true
    declare_exchange "dlx.retry" "direct" true
    
    # 2. Dead Letter Queue'ları oluştur
    log_info "--- Dead Letter Queue'lar oluşturuluyor ---"
    declare_queue "dlq.freecad" true "" "" ""
    declare_queue "dlq.sim" true "" "" ""
    declare_queue "dlq.cpu" true "" "" ""
    declare_queue "dlq.postproc" true "" "" ""
    declare_queue "dlq.retry" true "" "" ""
    
    # 3. Ana Celery queue'larını DLX ile oluştur
    log_info "--- Ana Celery Queue'lar oluşturuluyor (DLX ile) ---"
    # FreeCAD queue - 20 dakika TTL, 3 retry
    declare_queue "freecad" true "dlx" "freecad" 1200000 3
    
    # Simulation queue - 20 dakika TTL, 3 retry  
    declare_queue "sim" true "dlx" "sim" 1200000 3
    
    # CPU intensive tasks - 10 dakika TTL, 5 retry
    declare_queue "cpu" true "dlx" "cpu" 600000 5
    
    # Post-processing tasks - 5 dakika TTL, 5 retry
    declare_queue "postproc" true "dlx" "postproc" 300000 5
    
    # Retry queue - 2 dakika TTL, no further DLX
    declare_queue "retry" true "dlx.retry" "retry" 120000 0
    
    # 4. DLX binding'leri oluştur
    log_info "--- DLX Binding'ler oluşturuluyor ---"
    create_binding "dlx" "dlq.freecad" "freecad" "queue"
    create_binding "dlx" "dlq.sim" "sim" "queue"
    create_binding "dlx" "dlq.cpu" "cpu" "queue"
    create_binding "dlx" "dlq.postproc" "postproc" "queue"
    create_binding "dlx.retry" "dlq.retry" "retry" "queue"
    
    # 5. Celery default exchange ve binding'ler
    log_info "--- Celery Exchange ve Binding'ler oluşturuluyor ---"
    declare_exchange "celery" "direct" true
    
    create_binding "celery" "freecad" "freecad" "queue"
    create_binding "celery" "sim" "sim" "queue"  
    create_binding "celery" "cpu" "cpu" "queue"
    create_binding "celery" "postproc" "postproc" "queue"
    create_binding "celery" "retry" "retry" "queue"
    
    # 6. Queue politikaları
    log_info "--- Queue Politikaları uygulanıyor ---"
    
    # HA politikası - tüm queue'lar için
    declare_policy "ha-freecad-queues" ".*" '{"ha-mode":"all","ha-sync-mode":"automatic"}' 10 "queues"
    
    # DLQ için özel politika - mesaj TTL yok, sonsuz tutma
    declare_policy "dlq-policy" "dlq\..*" '{"message-ttl":null,"expires":null}' 20 "queues"
    
    # FreeCAD ve Sim için özel performans politikaları
    declare_policy "freecad-policy" "^(freecad|sim)$" '{"max-length":1000,"overflow":"reject-publish"}' 15 "queues"
    
    # CPU intensive için paralel işleme politikası  
    declare_policy "cpu-policy" "^(cpu|postproc)$" '{"max-length":5000,"overflow":"drop-head"}' 15 "queues"
    
    # 7. User permissions
    log_info "--- User Permissions ayarlanıyor ---"
    set_permissions "${RABBITMQ_USER}" ".*" ".*" ".*"
    
    # 8. Monitoring exchange (opsiyonel)
    log_info "--- Monitoring Exchange oluşturuluyor ---"
    declare_exchange "monitoring" "topic" true
    declare_queue "monitoring.logs" true "" "" ""
    create_binding "monitoring" "monitoring.logs" "task.*" "queue"
    
    log_info "=== RabbitMQ DLX Konfigürasyonu tamamlandı! ==="
    log_info ""
    log_info "Konfigüre edilen queue'lar:"
    log_info "  ✓ freecad (DLX: dlx -> dlq.freecad)"
    log_info "  ✓ sim (DLX: dlx -> dlq.sim)"  
    log_info "  ✓ cpu (DLX: dlx -> dlq.cpu)"
    log_info "  ✓ postproc (DLX: dlx -> dlq.postproc)"
    log_info "  ✓ retry (DLX: dlx.retry -> dlq.retry)"
    log_info ""
    log_info "Management UI: http://${RABBITMQ_HOST}:${RABBITMQ_MGMT_PORT}"
    log_info "Username: ${RABBITMQ_USER}"
    log_info "Password: ${RABBITMQ_PASS}"
    log_info ""
    log_info "DLQ'ları kontrol etmek için:"
    log_info "  make rabbitmq-status"
    log_info "  make dlq-status"
}

# Script'in ana fonksiyonu
main() {
    case "${1:-setup}" in
        "setup"|"")
            setup_rabbitmq
            ;;
        "status")
            log_info "RabbitMQ Status kontrol ediliyor..."
            curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
                 -s "${MGMT_API}/overview" | \
                 jq -r '.queue_totals | "Messages: \(.messages), Ready: \(.messages_ready), Unacked: \(.messages_unacknowledged)"'
            ;;
        "dlq-status")
            log_info "Dead Letter Queue Status:"
            curl -u "${RABBITMQ_USER}:${RABBITMQ_PASS}" \
                 -s "${MGMT_API}/queues" | \
                 jq -r '.[] | select(.name | startswith("dlq.")) | "\(.name): \(.messages) messages"'
            ;;
        "help")
            echo "Kullanım: $0 [setup|status|dlq-status|help]"
            echo ""
            echo "Komutlar:"
            echo "  setup      - RabbitMQ DLX konfigürasyonu (varsayılan)"
            echo "  status     - RabbitMQ genel durumu"  
            echo "  dlq-status - Dead Letter Queue durumu"
            echo "  help       - Bu yardım mesajı"
            ;;
        *)
            log_error "Bilinmeyen komut: $1"
            echo "Yardım için: $0 help"
            exit 1
            ;;
    esac
}

# Script çalıştırılıyorsa main fonksiyonu çağır
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi