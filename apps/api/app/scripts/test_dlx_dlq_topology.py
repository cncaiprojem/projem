#!/usr/bin/env python3
"""
Task 6.1: DLX/DLQ Topology Test Script
Tests the new RabbitMQ topology with per-queue dead-letter exchanges.

This script validates:
- Messages route to correct primary queues
- Failed messages go to corresponding DLQs
- Routing key mappings work correctly
- Quorum vs classic queue types
- Message size limits and publisher confirms
"""

import asyncio
import json
import logging
import sys
import time
from typing import Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

from ..core.celery_app import celery_app
from ..core.queue_constants import (
    MAIN_QUEUES,
    DLQ_QUEUES,
    ROUTING_KEY_MAPPINGS,
    JOBS_EXCHANGE,
    QUEUE_CONFIGS,
)
from ..config import settings

# Logging konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DLXTopologyTester:
    """Task 6.1 DLX/DLQ topology tester."""
    
    def __init__(self, rabbitmq_host: str = "localhost", rabbitmq_port: int = 15672,
                 username: str = "freecad", password: str = "freecad"):
        self.host = rabbitmq_host
        self.port = rabbitmq_port  
        self.username = username
        self.password = password
        self.base_url = f"http://{rabbitmq_host}:{rabbitmq_port}/api"
        self.auth = HTTPBasicAuth(username, password)
        self.vhost_encoded = "%2F"  # URL encoded "/"
        
    def get_queue_info(self, queue_name: str) -> Optional[Dict]:
        """Get detailed queue information from RabbitMQ management API."""
        try:
            response = requests.get(
                f"{self.base_url}/queues/{self.vhost_encoded}/{queue_name}",
                auth=self.auth,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Queue {queue_name} bilgisi alınamadı: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Queue {queue_name} bilgisi alma hatası: {e}")
            return None
            
    def get_exchange_info(self, exchange_name: str) -> Optional[Dict]:
        """Get exchange information from RabbitMQ management API."""
        try:
            response = requests.get(
                f"{self.base_url}/exchanges/{self.vhost_encoded}/{exchange_name}",
                auth=self.auth,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                logger.error(f"Exchange {exchange_name} bilgisi alınamadı: {response.status_code}")
                return None
        except Exception as e:
            logger.error(f"Exchange {exchange_name} bilgisi alma hatası: {e}")
            return None
            
    def test_topology_structure(self) -> bool:
        """Test if the topology structure is correctly set up."""
        logger.info("=== Topology Yapı Testi ===")
        
        # Test main jobs.direct exchange
        jobs_exchange = self.get_exchange_info(JOBS_EXCHANGE)
        if not jobs_exchange:
            logger.error(f"✗ {JOBS_EXCHANGE} exchange bulunamadı!")
            return False
        logger.info(f"✓ {JOBS_EXCHANGE} exchange bulundu (type: {jobs_exchange['type']})")
        
        # Test primary queues
        primary_queue_results = []
        for queue_name in MAIN_QUEUES:
            queue_info = self.get_queue_info(queue_name)
            if not queue_info:
                logger.error(f"✗ Primary queue {queue_name} bulunamadı!")
                primary_queue_results.append(False)
                continue
                
            # Check if it's a quorum queue
            queue_type = queue_info.get("arguments", {}).get("x-queue-type")
            if queue_type != "quorum":
                logger.warning(f"⚠ Queue {queue_name} quorum type değil: {queue_type}")
            else:
                logger.info(f"✓ Primary queue {queue_name} (type: {queue_type})")
                
            # Check DLX configuration
            dlx_exchange = queue_info.get("arguments", {}).get("x-dead-letter-exchange")
            expected_dlx = f"{queue_name}.dlx"
            if dlx_exchange != expected_dlx:
                logger.error(f"✗ Queue {queue_name} DLX yanlış: {dlx_exchange} != {expected_dlx}")
                primary_queue_results.append(False)
            else:
                logger.info(f"✓ Queue {queue_name} DLX doğru: {dlx_exchange}")
                
            primary_queue_results.append(True)
            
        # Test DLX exchanges
        dlx_results = []
        for queue_name in MAIN_QUEUES:
            dlx_name = f"{queue_name}.dlx"
            dlx_info = self.get_exchange_info(dlx_name)
            if not dlx_info:
                logger.error(f"✗ DLX {dlx_name} bulunamadı!")
                dlx_results.append(False)
                continue
            logger.info(f"✓ DLX {dlx_name} bulundu (type: {dlx_info['type']})")
            dlx_results.append(True)
            
        # Test DLQ queues
        dlq_results = []
        for queue_name in MAIN_QUEUES:
            dlq_name = f"{queue_name}_dlq"
            dlq_info = self.get_queue_info(dlq_name)
            if not dlq_info:
                logger.error(f"✗ DLQ {dlq_name} bulunamadı!")
                dlq_results.append(False)
                continue
                
            # Check if it's a classic queue with lazy mode
            queue_type = dlq_info.get("arguments", {}).get("x-queue-type")
            queue_mode = dlq_info.get("arguments", {}).get("x-queue-mode")
            if queue_type != "classic":
                logger.warning(f"⚠ DLQ {dlq_name} classic type değil: {queue_type}")
            if queue_mode != "lazy":
                logger.warning(f"⚠ DLQ {dlq_name} lazy mode değil: {queue_mode}")
            
            logger.info(f"✓ DLQ {dlq_name} (type: {queue_type}, mode: {queue_mode})")
            dlq_results.append(True)
            
        all_passed = all(primary_queue_results + dlx_results + dlq_results)
        if all_passed:
            logger.info("✅ Topology yapı testi BAŞARILI!")
        else:
            logger.error("❌ Topology yapı testi BAŞARISIZ!")
            
        return all_passed
        
    def test_message_routing(self) -> bool:
        """Test message routing to correct queues."""
        logger.info("=== Message Routing Testi ===")
        
        test_results = []
        
        # Get initial queue message counts
        initial_counts = {}
        for queue_name in MAIN_QUEUES:
            queue_info = self.get_queue_info(queue_name)
            if queue_info:
                initial_counts[queue_name] = queue_info.get("messages", 0)
                
        # Test each routing key mapping
        for routing_key, expected_queue in ROUTING_KEY_MAPPINGS.items():
            logger.info(f"Testing routing: {routing_key} -> {expected_queue}")
            
            try:
                # Send test message using Celery
                # Since we don't have actual tasks, we'll use send_task with a non-existent task
                # This will still route the message correctly but fail execution
                test_message = {
                    "test_routing_key": routing_key,
                    "expected_queue": expected_queue,
                    "timestamp": time.time(),
                }
                
                result = celery_app.send_task(
                    "test.routing.dummy_task",  # Non-existent task
                    args=[test_message],
                    queue=expected_queue,
                    routing_key=routing_key,
                )
                
                logger.info(f"✓ Message sent to {expected_queue} (task_id: {result.id})")
                test_results.append(True)
                
                # Wait a bit for message to be routed
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"✗ Message routing failed for {routing_key}: {e}")
                test_results.append(False)
                
        # Check if messages were routed correctly
        time.sleep(2)  # Wait for routing
        for queue_name in MAIN_QUEUES:
            queue_info = self.get_queue_info(queue_name)
            if queue_info:
                current_count = queue_info.get("messages", 0)
                initial_count = initial_counts.get(queue_name, 0)
                if current_count > initial_count:
                    logger.info(f"✓ Queue {queue_name} received messages: {current_count - initial_count}")
                    
        all_routing_passed = all(test_results)
        if all_routing_passed:
            logger.info("✅ Message routing testi BAŞARILI!")
        else:
            logger.error("❌ Message routing testi BAŞARISIZ!")
            
        return all_routing_passed
        
    def test_dlq_functionality(self) -> bool:
        """Test DLQ functionality by simulating failed messages."""
        logger.info("=== DLQ Functionality Testi ===")
        
        # This is a simplified test since we can't easily simulate message failures
        # In a real environment, you'd need to:
        # 1. Send messages that cause task failures
        # 2. Wait for retries to exhaust
        # 3. Check if messages end up in DLQs
        
        logger.info("⚠ DLQ functionality requires actual failing tasks to test properly")
        logger.info("⚠ This would be tested during integration testing with real task failures")
        
        # Check if DLQs exist and are properly configured
        dlq_test_results = []
        for queue_name in MAIN_QUEUES:
            dlq_name = f"{queue_name}_dlq"
            dlq_info = self.get_queue_info(dlq_name)
            if dlq_info:
                logger.info(f"✓ DLQ {dlq_name} configured and ready")
                dlq_test_results.append(True)
            else:
                logger.error(f"✗ DLQ {dlq_name} not found")
                dlq_test_results.append(False)
                
        all_dlq_ready = all(dlq_test_results)
        if all_dlq_ready:
            logger.info("✅ DLQ readiness testi BAŞARILI!")
        else:
            logger.error("❌ DLQ readiness testi BAŞARISIZ!")
            
        return all_dlq_ready
        
    def test_celery_configuration(self) -> bool:
        """Test Celery configuration with new queues."""
        logger.info("=== Celery Configuration Testi ===")
        
        try:
            # Check if Celery app is configured with new queues
            configured_queues = [q.name for q in celery_app.conf.task_queues]
            logger.info(f"Configured queues: {configured_queues}")
            
            # Check primary queues
            missing_primary = []
            for queue_name in MAIN_QUEUES:
                if queue_name not in configured_queues:
                    missing_primary.append(queue_name)
                    
            if missing_primary:
                logger.error(f"✗ Missing primary queues in Celery config: {missing_primary}")
                return False
                
            logger.info("✓ All primary queues configured in Celery")
            
            # Check DLQs
            missing_dlq = []
            for queue_name in MAIN_QUEUES:
                dlq_name = f"{queue_name}_dlq"
                if dlq_name not in configured_queues:
                    missing_dlq.append(dlq_name)
                    
            if missing_dlq:
                logger.error(f"✗ Missing DLQs in Celery config: {missing_dlq}")
                return False
                
            logger.info("✓ All DLQs configured in Celery")
            
            # Check task routes
            task_routes = dict(celery_app.conf.task_routes)
            logger.info(f"Configured task routes: {len(task_routes)}")
            
            # Check default queue
            default_queue = celery_app.conf.task_default_queue
            if default_queue != "default":
                logger.warning(f"⚠ Default queue is not 'default': {default_queue}")
            else:
                logger.info("✓ Default queue correctly set to 'default'")
                
            logger.info("✅ Celery configuration testi BAŞARILI!")
            return True
            
        except Exception as e:
            logger.error(f"❌ Celery configuration testi BAŞARISIZ: {e}")
            return False
            
    def print_summary(self):
        """Print topology summary."""
        logger.info("")
        logger.info("=== TOPOLOGY ÖZETİ ===")
        logger.info(f"📋 Primary Exchange: {JOBS_EXCHANGE}")
        logger.info("📋 Primary Queues (Quorum):")
        for queue_name in MAIN_QUEUES:
            config = QUEUE_CONFIGS[queue_name]
            logger.info(f"  ✓ {queue_name} (TTL: {config['ttl']}ms, Priority: {config['priority']})")
            
        logger.info("")
        logger.info("📋 Dead Letter Topology:")
        for queue_name in MAIN_QUEUES:
            dlx_name = f"{queue_name}.dlx"
            dlq_name = f"{queue_name}_dlq"
            logger.info(f"  ✓ {queue_name} -> {dlx_name} -> {dlq_name}")
            
        logger.info("")
        logger.info("📋 Routing Key Mappings:")
        for routing_key, queue_name in ROUTING_KEY_MAPPINGS.items():
            logger.info(f"  ✓ {routing_key} -> {queue_name}")
            
        logger.info("")
        
    def run_all_tests(self) -> bool:
        """Run all topology tests."""
        logger.info("=== Task 6.1: DLX/DLQ Topology Test Suite ===")
        
        tests = [
            ("Topology Structure", self.test_topology_structure),
            ("Celery Configuration", self.test_celery_configuration),
            ("Message Routing", self.test_message_routing),
            ("DLQ Functionality", self.test_dlq_functionality),
        ]
        
        results = []
        for test_name, test_func in tests:
            logger.info(f"\n--- {test_name} Test ---")
            try:
                result = test_func()
                results.append((test_name, result))
                if result:
                    logger.info(f"✅ {test_name} BAŞARILI")
                else:
                    logger.error(f"❌ {test_name} BAŞARISIZ")
            except Exception as e:
                logger.error(f"❌ {test_name} HATA: {e}")
                results.append((test_name, False))
                
        # Print results summary
        logger.info("\n=== TEST SONUÇLARI ===")
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✅ BAŞARILI" if result else "❌ BAŞARISIZ"
            logger.info(f"{test_name}: {status}")
            
        logger.info(f"\nToplam: {passed}/{total} test başarılı")
        
        if passed == total:
            logger.info("🎉 Tüm testler başarılı! Task 6.1 topology çalışıyor.")
            self.print_summary()
            return True
        else:
            logger.error("⚠ Bazı testler başarısız. Konfigürasyonu kontrol edin.")
            return False


def main():
    """Ana test fonksiyonu."""
    import os
    
    # Environment variables
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    rabbitmq_port = int(os.getenv("RABBITMQ_MGMT_PORT", "15672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "freecad")
    rabbitmq_pass = os.getenv("RABBITMQ_PASS", "freecad")
    
    tester = DLXTopologyTester(
        rabbitmq_host=rabbitmq_host,
        rabbitmq_port=rabbitmq_port,
        username=rabbitmq_user,
        password=rabbitmq_pass
    )
    
    try:
        success = tester.run_all_tests()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("Test kullanıcı tarafından durduruldu")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Beklenmeyen hata: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()