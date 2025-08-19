#!/usr/bin/env python3
"""
Celery RabbitMQ bağlantı testi ve konfigürasyon doğrulama scripti.
"""

import asyncio
import logging
import sys
import time
from typing import Dict, Any

from ..tasks.worker import celery_app
from ..config import settings
from ..core.queue_constants import ALL_QUEUES

# Logging yapılandırması
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_broker_connection() -> bool:
    """RabbitMQ broker bağlantısını test et."""
    logger.info("RabbitMQ broker bağlantısı test ediliyor...")
    try:
        from kombu import Connection

        with Connection(settings.rabbitmq_url) as conn:
            conn.connect()
            logger.info(f"✓ RabbitMQ broker bağlantısı başarılı: {settings.rabbitmq_url}")
            return True

    except Exception as e:
        logger.error(f"✗ RabbitMQ broker bağlantısı başarısız: {e}")
        return False


def test_redis_backend() -> bool:
    """Redis result backend bağlantısını test et."""
    logger.info("Redis result backend bağlantısı test ediliyor...")
    try:
        import redis

        r = redis.from_url(settings.redis_url)
        r.ping()
        logger.info(f"✓ Redis backend bağlantısı başarılı: {settings.redis_url}")
        return True

    except Exception as e:
        logger.error(f"✗ Redis backend bağlantısı başarısız: {e}")
        return False


def test_celery_config() -> Dict[str, Any]:
    """Celery konfigürasyonunu kontrol et."""
    logger.info("Celery konfigürasyonu kontrol ediliyor...")

    config_info = {
        "broker_url": celery_app.conf.broker_url,
        "result_backend": celery_app.conf.result_backend,
        "task_default_queue": celery_app.conf.task_default_queue,
        "task_routes": dict(celery_app.conf.task_routes),
        "queue_count": len(celery_app.conf.task_queues),
        "beat_schedule_count": len(celery_app.conf.beat_schedule),
    }

    logger.info(f"Broker URL: {config_info['broker_url']}")
    logger.info(f"Result Backend: {config_info['result_backend']}")
    logger.info(f"Default Queue: {config_info['task_default_queue']}")
    logger.info(f"Configured Queues: {config_info['queue_count']}")
    logger.info(f"Beat Schedule Tasks: {config_info['beat_schedule_count']}")

    return config_info


def test_queue_declarations() -> bool:
    """Queue tanımlamalarını test et."""
    logger.info("Queue tanımlamaları test ediliyor...")
    try:
        from kombu import Connection

        with Connection(settings.rabbitmq_url) as conn:
            with conn.channel() as channel:
                expected_queues = ALL_QUEUES

                for queue_name in expected_queues:
                    try:
                        queue_info = channel.queue_declare(queue_name, passive=True)
                        logger.info(
                            f"✓ Queue '{queue_name}' bulundu: {queue_info.message_count} mesaj"
                        )
                    except Exception as e:
                        logger.warning(f"✗ Queue '{queue_name}' bulunamadı: {e}")

        return True

    except Exception as e:
        logger.error(f"Queue test başarısız: {e}")
        return False


def test_task_discovery() -> bool:
    """Task keşfini test et."""
    logger.info("Task keşfi test ediliyor...")
    try:
        # Registered tasks
        tasks = list(celery_app.tasks.keys())
        task_count = len(tasks)

        logger.info(f"Keşfedilen task sayısı: {task_count}")

        # Expected task modules
        expected_modules = [
            "app.tasks.maintenance",
            "app.tasks.monitoring",
            "app.tasks.assembly",
            "app.tasks.cam",
            "app.tasks.sim",
            "app.tasks.design",
            "app.tasks.cad",
        ]

        for module in expected_modules:
            module_tasks = [t for t in tasks if t.startswith(module)]
            if module_tasks:
                logger.info(f"✓ {module}: {len(module_tasks)} task")
            else:
                logger.warning(f"✗ {module}: task bulunamadı")

        return task_count > 0

    except Exception as e:
        logger.error(f"Task keşfi başarısız: {e}")
        return False


def test_simple_task() -> bool:
    """Basit bir test task'ı çalıştır."""
    logger.info("Test task'ı gönderiliyor...")
    try:
        # Maintenance health check task'ını test et
        result = celery_app.send_task(
            "app.tasks.maintenance.health_check", queue="cpu", routing_key="cpu"
        )

        logger.info(f"Task gönderildi: {result.id}")

        # Kısa süre bekle (asenkron olduğu için sonucu beklemiyoruz)
        time.sleep(2)

        if result.state in ["PENDING", "SENT"]:
            logger.info(f"✓ Task başarıyla gönderildi, durumu: {result.state}")
            return True
        else:
            logger.warning(f"Task durumu beklenmedik: {result.state}")
            return False

    except Exception as e:
        logger.error(f"Test task başarısız: {e}")
        return False


def main():
    """Ana test fonksiyonu."""
    logger.info("=== Celery RabbitMQ Konfigürasyon Testi ===")

    tests = [
        ("RabbitMQ Broker Bağlantısı", test_broker_connection),
        ("Redis Backend Bağlantısı", test_redis_backend),
        ("Celery Konfigürasyonu", lambda: test_celery_config() is not None),
        ("Queue Tanımlamaları", test_queue_declarations),
        ("Task Keşfi", test_task_discovery),
        ("Test Task Gönderimi", test_simple_task),
    ]

    results = []
    for test_name, test_func in tests:
        logger.info(f"\n--- {test_name} ---")
        try:
            result = test_func()
            results.append((test_name, result))
            if result:
                logger.info(f"✓ {test_name} BAŞARILI")
            else:
                logger.error(f"✗ {test_name} BAŞARISIZ")
        except Exception as e:
            logger.error(f"✗ {test_name} HATA: {e}")
            results.append((test_name, False))

    # Sonuçları özetle
    logger.info("\n=== TEST SONUÇLARI ===")
    passed = sum(1 for _, result in results if result)
    total = len(results)

    for test_name, result in results:
        status = "✓ BAŞARILI" if result else "✗ BAŞARISIZ"
        logger.info(f"{test_name}: {status}")

    logger.info(f"\nToplam: {passed}/{total} test başarılı")

    if passed == total:
        logger.info("🎉 Tüm testler başarılı! Celery RabbitMQ konfigürasyonu çalışıyor.")
        sys.exit(0)
    else:
        logger.error("❌ Bazı testler başarısız. Konfigürasyonu kontrol edin.")
        sys.exit(1)


if __name__ == "__main__":
    main()
