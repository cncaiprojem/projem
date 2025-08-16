# RabbitMQ Dead Letter Exchange (DLX) Konfigürasyonu

Bu döküman, FreeCAD CNC/CAM platformu için RabbitMQ Dead Letter Exchange konfigürasyonunu açıklar.

## Genel Bakış

RabbitMQ, Celery task queue sistemi için ana message broker olarak kullanılır. Dead Letter Exchange (DLX) konfigürasyonu ile başarısız taskların güvenli bir şekilde işlenmesi sağlanır.

## Kurulum

### 1. Hızlı Başlangıç

```bash
# Tüm sistemi development modunda başlat
make dev-full

# RabbitMQ DLX konfigürasyonunu uygula
make rabbitmq-setup

# RabbitMQ durumunu kontrol et
make rabbitmq-status
```

### 2. Production Kurulumu

```bash
# Production stack'i başlat
make dev

# RabbitMQ konfigürasyonunu uygula
make rabbitmq-setup
```

## Queue Yapısı

### Ana Queue'lar

| Queue Name | Purpose | Concurrency | TTL | DLX |
|------------|---------|-------------|-----|-----|
| `freecad` | FreeCAD CAD işlemleri | 1 | 20 min | dlx |
| `sim` | CAM simülasyonları | 1 | 20 min | dlx |
| `cpu` | CPU-intensive tasklar | 4 | 10 min | dlx |
| `postproc` | Post-processing | 4 | 5 min | dlx |
| `retry` | Yeniden deneme taskları | 2 | 2 min | dlx.retry |

### Dead Letter Queue'lar

| DLQ Name | Source Queue | Purpose |
|----------|--------------|---------|
| `dlq.freecad` | freecad | Başarısız FreeCAD taskları |
| `dlq.sim` | sim | Başarısız simülasyon taskları |
| `dlq.cpu` | cpu | Başarısız CPU taskları |
| `dlq.postproc` | postproc | Başarısız post-processing |
| `dlq.retry` | retry | Son deneme sonrası başarısız |

## DLX Akışı

```
1. Task gönderilir → Ana Queue (örn: freecad)
2. Worker task'ı işler
3. Başarısızlık durumunda:
   - Max retry sayısı kontrol edilir
   - TTL süresi dolmuşsa → DLX'e yönlendirilir
   - DLX'den DLQ'ya (örn: dlq.freecad) routing yapılır
4. Admin/monitoring tools DLQ'ları inceleyebilir
```

## Monitoring ve Yönetim

### RabbitMQ Management UI

```bash
# Management UI'yi aç
make rabbitmq-ui

# Manuel erişim:
# URL: http://localhost:15672
# Username: freecad
# Password: freecad
```

### Komut Satırı Monitoring

```bash
# Genel RabbitMQ durumu
make rabbitmq-status

# Dead Letter Queue durumu
make dlq-status

# Detaylı queue bilgileri
docker exec fc_rabbitmq rabbitmqctl list_queues name messages consumers

# Exchange bilgileri
docker exec fc_rabbitmq rabbitmqctl list_exchanges name type
```

## Güvenlik Özellikleri

### Container Security

- `security_opt: no-new-privileges:true` - Privilege escalation engelleme
- Non-root user olarak çalışma
- Read-only file system (mümkün olduğunda)

### Network Security

- Internal Docker network kullanımı
- Management port'u sadece development'ta expose
- TLS/SSL desteği (production için)

### Access Control

- Dedicated kullanıcı (`freecad`)
- VHost izolasyonu
- Queue-level permissions

## Development vs Production

### Development (`docker-compose.dev.yml`)

- Tüm port'lar expose edilir
- Detaylı logging aktif
- Development-specific plugins
- Hot reload desteği
- Debug mode aktif
- Local volume mount'lar

### Production (`docker-compose.yml`)

- Minimal port exposure
- Production-level logging
- Optimized memory/CPU settings
- Health check'ler
- Restart policies
- Security hardening

## Konfigürasyon Dosyaları

```
scripts/
├── init-rabbitmq.sh          # DLX ve queue setup script'i
└── ...

compose/
├── rabbitmq-dev-plugins.txt  # Development plugin'leri
└── ...

docker-compose.yml             # Production konfigürasyonu
docker-compose.dev.yml         # Development overrides
.env                           # Environment variables
```

## Environment Variables

```bash
# RabbitMQ Configuration
RABBITMQ_USER=freecad                    # RabbitMQ kullanıcı adı
RABBITMQ_PASS=freecad                    # RabbitMQ şifresi
RABBITMQ_VHOST=/                         # Virtual host
RABBITMQ_PORT=5672                       # AMQP port
RABBITMQ_MGMT_PORT=15672                 # Management UI port
RABBITMQ_URL=amqp://freecad:freecad@rabbitmq:5672/
```

## Sorun Giderme

### Yaygın Sorunlar

#### 1. RabbitMQ Başlatılamıyor

```bash
# Container log'larını kontrol et
docker logs fc_rabbitmq

# Health check durumu
docker inspect fc_rabbitmq | grep Health -A 10

# Port çakışması kontrol et
netstat -tulpn | grep :5672
```

#### 2. Queue'lar Oluşturulmuyor

```bash
# Manuel setup çalıştır
make rabbitmq-setup

# Script'i debug mode'da çalıştır
docker exec fc_rabbitmq bash /docker-entrypoint-initdb.d/init-rabbitmq.sh setup
```

#### 3. DLX Çalışmıyor

```bash
# Exchange'leri kontrol et
docker exec fc_rabbitmq rabbitmqctl list_exchanges name type

# Binding'leri kontrol et
docker exec fc_rabbitmq rabbitmqctl list_bindings

# Policy'leri kontrol et
docker exec fc_rabbitmq rabbitmqctl list_policies
```

#### 4. Worker'lar Bağlanamıyor

```bash
# Network bağlantısını kontrol et
docker exec fc_worker ping rabbitmq

# Environment variable'ları kontrol et
docker exec fc_worker env | grep RABBITMQ

# Celery broker connectivity test
docker exec fc_worker celery -A app.tasks.worker inspect ping
```

### Log Analizi

```bash
# RabbitMQ log'ları
docker logs fc_rabbitmq -f

# Worker log'ları
docker logs fc_worker -f
docker logs fc_worker_freecad -f
docker logs fc_worker_sim -f

# Celery beat log'ları
docker logs fc_beat -f
```

## Performance İpuçları

### Queue Optimizasyonu

1. **Concurrency Ayarları**
   - FreeCAD: 1 (memory intensive)
   - Simulation: 1 (CPU+memory intensive)
   - CPU tasks: 4 (parallelizable)
   - Post-processing: 4 (lightweight)

2. **TTL Ayarları**
   - FreeCAD/Sim: 20 min (complex operations)
   - CPU: 10 min (medium complexity)
   - Post-processing: 5 min (fast operations)

3. **Memory Management**
   - `x-max-length` policies uygulanır
   - `overflow` behavior configured
   - Dead letter retention policies

### Monitoring Metrikleri

- Queue depth (messages waiting)
- Consumer count (active workers)
- Processing rate (messages/second)
- Error rate (% failed tasks)
- DLQ accumulation (failed message count)

## Backup ve Recovery

### Queue State Backup

```bash
# Export definitions
docker exec fc_rabbitmq rabbitmqctl export_definitions /tmp/definitions.json

# Copy to host
docker cp fc_rabbitmq:/tmp/definitions.json ./backup/
```

### Recovery

```bash
# Import definitions
docker exec fc_rabbitmq rabbitmqctl import_definitions /tmp/definitions.json
```

## Integration Testing

RabbitMQ entegrasyonunu test etmek için:

```bash
# Test suite çalıştır
make test

# RabbitMQ specific testler
docker exec fc_api pytest tests/integration/test_rabbitmq.py -v

# End-to-end queue testing
docker exec fc_api python -m app.scripts.test_queue_flow
```

## Üretim Deployment

Kubernetes ortamında deployment için `charts/cnc/` klasöründeki Helm chart'ları kullanın. RabbitMQ için StatefulSet ve PersistentVolume konfigürasyonları mevcuttur.

## Referanslar

- [RabbitMQ Documentation](https://www.rabbitmq.com/documentation.html)
- [Celery with RabbitMQ](https://docs.celeryproject.org/en/stable/getting-started/brokers/rabbitmq.html)
- [Docker RabbitMQ](https://hub.docker.com/_/rabbitmq)
- [Dead Letter Exchanges](https://www.rabbitmq.com/dlx.html)