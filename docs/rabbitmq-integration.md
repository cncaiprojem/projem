# RabbitMQ Integration Guide

Bu dokümantasyon, FreeCAD CNC/CAM platform'unda Celery worker'larının RabbitMQ ile entegrasyonunu açıklar.

## Genel Bakış

Sistem artık Redis yerine RabbitMQ'yu Celery broker olarak kullanır:
- **Broker**: RabbitMQ (mesaj kuyruğu)
- **Result Backend**: Redis (sonuç saklama)
- **Dead Letter Exchange (DLX)**: Başarısız task'lar için
- **Queue Prioritization**: Öncelik bazlı task işleme

## Mimarı

### Queue Yapısı

```
freecad (Queue)          -> dlx (Exchange) -> dlq.freecad (DLQ)
├── Priority: 7 (High)
├── TTL: 20 dakika
└── Max Retry: 3

sim (Queue)              -> dlx (Exchange) -> dlq.sim (DLQ)
├── Priority: 7 (High)
├── TTL: 20 dakika
└── Max Retry: 3

cpu (Queue)              -> dlx (Exchange) -> dlq.cpu (DLQ)
├── Priority: 5 (Normal)
├── TTL: 10 dakika
└── Max Retry: 5

postproc (Queue)         -> dlx (Exchange) -> dlq.postproc (DLQ)
├── Priority: 3 (Low)
├── TTL: 5 dakika
└── Max Retry: 5
```

### Task Routing

| Task Module | Queue | Priority | Açıklama |
|-------------|-------|----------|----------|
| `app.tasks.assembly.*` | freecad | 9 (Urgent) | Assembly generation |
| `app.tasks.cad.*` | freecad | 7 (High) | CAD modeling |
| `app.tasks.cam_build.*` | freecad | 7 (High) | CAM build operations |
| `app.tasks.m18_cam.*` | freecad | 7 (High) | M18 CAM processing |
| `app.tasks.m18_sim.*` | sim | 7 (High) | M18 simulation |
| `app.tasks.sim.*` | sim | 5 (Normal) | General simulation |
| `app.tasks.cam.*` | cpu | 5 (Normal) | CAM operations |
| `app.tasks.design.*` | cpu | 5 (Normal) | Design operations |
| `app.tasks.m18_post.*` | postproc | 3 (Low) | Post-processing |
| `app.tasks.reports.*` | postproc | 3 (Low) | Report generation |
| `app.tasks.maintenance.*` | postproc | 1 (Background) | System maintenance |
| `app.tasks.monitoring.*` | cpu | 1 (Background) | System monitoring |

## Konfigürasyon

### Environment Variables

```bash
# RabbitMQ Broker
RABBITMQ_USER=freecad
RABBITMQ_PASS=freecad
RABBITMQ_VHOST=/
RABBITMQ_PORT=5672
RABBITMQ_MGMT_PORT=15672
RABBITMQ_URL=amqp://freecad:freecad@rabbitmq:5672/

# Celery Configuration
CELERY_WORKER_PREFETCH_MULTIPLIER=1
CELERY_TASK_ACKS_LATE=true
CELERY_BROKER_POOL_LIMIT=10

# Queue Priorities
QUEUE_PRIORITY_URGENT=9
QUEUE_PRIORITY_HIGH=7
QUEUE_PRIORITY_NORMAL=5
QUEUE_PRIORITY_LOW=3
QUEUE_PRIORITY_BACKGROUND=1
```

### Worker Konfigürasyonu

```bash
# CPU ve Post-processing workers
celery -A app.tasks.worker worker --loglevel=INFO -Q cpu,postproc -c 4

# FreeCAD workers (özel container)
celery -A app.tasks.worker worker --loglevel=INFO -Q freecad -c 1

# Simulation workers
celery -A app.tasks.worker worker --loglevel=INFO -Q sim -c 1

# Beat scheduler
celery -A app.tasks.worker beat --loglevel=INFO
```

## Dead Letter Exchange (DLX)

### DLX Akışı

1. **Normal Processing**: Task normal queue'da işlenir
2. **Failure/Timeout**: Task başarısız olursa DLX'e gönderilir
3. **DLQ Storage**: DLX mesajı ilgili DLQ'ya yönlendirir
4. **Manual Review**: DLQ'daki mesajlar manuel olarak incelenir
5. **Retry/Discard**: Mesaj tekrar kuyruğa alınır veya silinir

### DLQ Yönetimi

```bash
# DLQ durumunu kontrol et
make dlq-status

# RabbitMQ management UI
make rabbitmq-ui
# URL: http://localhost:15672
# User: freecad / Pass: freecad
```

## Celery Beat Schedule

Sistem otomatik olarak periyodik task'lar çalıştırır:

| Task | Schedule | Queue | Açıklama |
|------|----------|-------|----------|
| `health_check` | 5 dakika | cpu | Sistem sağlık kontrolü |
| `cleanup_temp_files` | 24 saat | postproc | Geçici dosya temizleme |
| `collect_queue_metrics` | 1 dakika | cpu | Queue metrik toplama |
| `cleanup_dlq` | 1 saat | postproc | DLQ temizleme |
| `freecad_health_check` | 10 dakika | freecad | FreeCAD sağlık kontrolü |

## Monitoring ve Metrics

### Task Metrics

- **Active Tasks**: Şu anda işlenen task sayısı
- **Pending Tasks**: Kuyrukta bekleyen task sayısı
- **Failed Tasks**: DLQ'ya düşen task sayısı
- **Worker Health**: Worker durumu ve kaynak kullanımı

### RabbitMQ Metrics

- **Queue Depth**: Her queue'daki mesaj sayısı
- **Consumer Count**: Her queue'ya bağlı consumer sayısı
- **Message Rate**: Saniye başına mesaj işleme oranı
- **DLQ Messages**: Dead letter queue'daki mesaj sayısı

## Geliştirme ve Test

### Test Scripti

```bash
# Celery RabbitMQ konfigürasyonunu test et
docker exec fc_api python -m app.scripts.test_celery_rabbitmq
```

### Manual Task Gönderimi

```python
from app.tasks.worker import celery_app

# Health check task'ı gönder
result = celery_app.send_task(
    "app.tasks.maintenance.health_check",
    queue="cpu",
    priority=5
)

print(f"Task ID: {result.id}")
```

### Worker Debug

```bash
# Worker loglarını izle
docker logs -f fc_worker
docker logs -f fc_worker_freecad
docker logs -f fc_worker_sim

# Celery inspect commands
docker exec fc_worker celery -A app.tasks.worker inspect active
docker exec fc_worker celery -A app.tasks.worker inspect stats
docker exec fc_worker celery -A app.tasks.worker inspect registered
```

## Performans Optimizasyonu

### Worker Scaling

```yaml
# infra/compose/docker-compose.dev.yml
worker:
  command: ["celery", "-A", "app.tasks.worker", "worker", "--loglevel=INFO", "-Q", "cpu,postproc", "-c", "4"]
  deploy:
    replicas: 2  # Horizontal scaling

worker-freecad:
  command: ["celery", "-A", "app.tasks.worker", "worker", "--loglevel=INFO", "-Q", "freecad", "-c", "1"]
  deploy:
    replicas: 3  # FreeCAD için ayrı scaling
```

### Queue Optimization

- **Priority Queues**: Kritik task'lar önce işlenir
- **TTL Settings**: Eski task'lar otomatik temizlenir
- **Connection Pooling**: Broker bağlantıları pool'lanır
- **Prefetch Limiting**: Memory kullanımı kontrol edilir

## Troubleshooting

### Sık Karşılaşılan Sorunlar

1. **RabbitMQ Connection Failed**
   ```bash
   # RabbitMQ servisini kontrol et
   docker ps | grep rabbitmq
   docker logs fc_rabbitmq
   
   # RabbitMQ kurulumunu yeniden çalıştır
   make rabbitmq-setup
   ```

2. **Tasks Not Processing**
   ```bash
   # Worker durumunu kontrol et
   docker exec fc_worker celery -A app.tasks.worker inspect ping
   
   # Queue durumunu kontrol et
   make rabbitmq-status
   ```

3. **High DLQ Count**
   ```bash
   # DLQ'yu temizle
   docker exec fc_rabbitmq /opt/rabbitmq/init-rabbitmq.sh dlq-status
   
   # Başarısız task'ları analiz et
   make dlq-status
   ```

4. **Memory Issues**
   ```bash
   # Worker memory kullanımını kontrol et
   docker stats fc_worker fc_worker_freecad fc_worker_sim
   
   # Prefetch multiplier'ı azalt
   CELERY_WORKER_PREFETCH_MULTIPLIER=1
   ```

### Debug Commands

```bash
# RabbitMQ Management UI
make rabbitmq-ui

# Queue ve worker durumu
make rabbitmq-status

# Test suite çalıştır
docker exec fc_api python -m app.scripts.test_celery_rabbitmq

# Worker logları (detailed)
docker exec fc_worker celery -A app.tasks.worker events
```

## Best Practices

1. **Task Design**
   - Idempotent task'lar yazın
   - Timeout değerlerini makul tutun
   - Retry logic'i ekleyin
   - Error handling implement edin

2. **Resource Management**
   - FreeCAD process'leri izleyin
   - Memory leak'leri engelleyin
   - Geçici dosyaları temizleyin
   - Connection pool'ları optimize edin

3. **Monitoring**
   - Queue depth'i izleyin
   - DLQ mesajlarını kontrol edin
   - Worker health'i takip edin
   - Performance metrikleri toplayın

4. **Security**
   - RabbitMQ credentials'ları güvenli tutun
   - Network segmentation kullanın
   - TLS/SSL aktif edin (production)
   - User permissions'ları kısıtlayın