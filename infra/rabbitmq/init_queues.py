#!/usr/bin/env python3
"""
Task 6.1: RabbitMQ Queue Topology Initialization Script
Creates the complete jobs.direct exchange topology with per-queue DLX/DLQ.

This script sets up:
- jobs.direct exchange for primary queues
- Per-queue dead letter exchanges (<queue>.dlx) 
- Dead letter queues (<queue>_dlq)
- Quorum queues for primaries, classic lazy for DLQs
- Message size limits (10MB) and publisher confirms
- Proper bindings and routing keys
"""

import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import requests
from requests.auth import HTTPBasicAuth

# Logging konfigürasyonu
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Task 6.1: Queue topology configuration
MAIN_QUEUES = ["default", "model", "cam", "sim", "report", "erp"]
JOBS_EXCHANGE = "jobs.direct"
DLX_SUFFIX = ".dlx"
DLQ_SUFFIX = "_dlq"

# Queue configurations per Task 6.1 requirements
QUEUE_CONFIGS = {
    "default": {
        "ttl": 1800000,  # 30 minutes
        "max_retries": 3,
        "priority": 5,  # normal
        "max_message_bytes": 10485760,  # 10MB
    },
    "model": {
        "ttl": 3600000,  # 1 hour
        "max_retries": 3,
        "priority": 7,  # high
        "max_message_bytes": 10485760,
    },
    "cam": {
        "ttl": 2700000,  # 45 minutes
        "max_retries": 3,
        "priority": 7,  # high
        "max_message_bytes": 10485760,
    },
    "sim": {
        "ttl": 3600000,  # 1 hour
        "max_retries": 3,
        "priority": 7,  # high
        "max_message_bytes": 10485760,
    },
    "report": {
        "ttl": 900000,  # 15 minutes
        "max_retries": 2,
        "priority": 3,  # low
        "max_message_bytes": 10485760,
    },
    "erp": {
        "ttl": 1800000,  # 30 minutes
        "max_retries": 2,
        "priority": 5,  # normal
        "max_message_bytes": 10485760,
    },
}

# DLQ configuration - classic lazy queues
DLQ_CONFIG = {
    "ttl": 86400000,  # 24 hours
    "max_length": 10000,
    "queue_mode": "lazy",
}

# Routing key mappings per Task 6.1
ROUTING_KEY_MAPPINGS = {
    "jobs.ai": "default",
    "jobs.model": "model", 
    "jobs.cam": "cam",
    "jobs.sim": "sim",
    "jobs.report": "report",
    "jobs.erp": "erp",
}


class RabbitMQInitializer:
    """RabbitMQ topology initializer for Task 6.1 requirements."""
    
    def __init__(self, host: str = "localhost", port: int = 15672,
                 username: str = "freecad", password: str = "freecad",
                 vhost: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.vhost = vhost
        self.base_url = f"http://{host}:{port}/api"
        self.auth = HTTPBasicAuth(username, password)
        
        # URL encode vhost
        self.vhost_encoded = vhost.replace("/", "%2F")
        
    def wait_for_rabbitmq(self, max_attempts: int = 30) -> bool:
        """RabbitMQ servisinin hazır olmasını bekle."""
        logger.info("RabbitMQ servisinin hazır olması bekleniyor...")
        
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(
                    f"{self.base_url}/aliveness-test/{self.vhost_encoded}",
                    auth=self.auth,
                    timeout=5
                )
                if response.status_code == 200:
                    logger.info(f"✓ RabbitMQ hazır! (Deneme: {attempt}/{max_attempts})")
                    return True
                    
            except Exception as e:
                logger.debug(f"RabbitMQ bağlantı hatası: {e}")
                
            logger.warning(f"RabbitMQ henüz hazır değil, bekleniyor... ({attempt}/{max_attempts})")
            time.sleep(2)
            
        logger.error(f"RabbitMQ {max_attempts} deneme sonrası hazır değil!")
        return False
        
    def declare_exchange(self, name: str, exchange_type: str = "direct",
                        durable: bool = True) -> bool:
        """Exchange oluştur."""
        logger.info(f"Exchange tanımlanıyor: {name} (type: {exchange_type})")
        
        payload = {
            "type": exchange_type,
            "durable": durable
        }
        
        try:
            response = requests.put(
                f"{self.base_url}/exchanges/{self.vhost_encoded}/{name}",
                auth=self.auth,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                logger.info(f"✓ Exchange '{name}' başarıyla oluşturuldu")
                return True
            else:
                logger.error(f"✗ Exchange '{name}' oluşturulamadı: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Exchange '{name}' oluşturma hatası: {e}")
            return False
            
    def declare_queue(self, name: str, durable: bool = True, 
                     queue_type: str = "quorum", arguments: Optional[Dict] = None) -> bool:
        """Queue oluştur."""
        logger.info(f"Queue tanımlanıyor: {name} (type: {queue_type})")
        
        payload = {
            "durable": durable,
            "arguments": arguments or {}
        }
        
        # Queue type'ı arguments'e ekle
        if queue_type:
            payload["arguments"]["x-queue-type"] = queue_type
            
        try:
            response = requests.put(
                f"{self.base_url}/queues/{self.vhost_encoded}/{name}",
                auth=self.auth,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                logger.info(f"✓ Queue '{name}' başarıyla oluşturuldu")
                return True
            else:
                logger.error(f"✗ Queue '{name}' oluşturulamadı: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Queue '{name}' oluşturma hatası: {e}")
            return False
            
    def create_binding(self, source: str, destination: str, routing_key: str = "",
                      destination_type: str = "queue") -> bool:
        """Binding oluştur."""
        logger.info(f"Binding oluşturuluyor: {source} -> {destination} (key: {routing_key})")
        
        payload = {
            "routing_key": routing_key
        }
        
        try:
            response = requests.post(
                f"{self.base_url}/bindings/{self.vhost_encoded}/e/{source}/{destination_type[0]}/{destination}",
                auth=self.auth,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                logger.info(f"✓ Binding '{source} -> {destination}' başarıyla oluşturuldu")
                return True
            else:
                logger.error(f"✗ Binding '{source} -> {destination}' oluşturulamadı: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Binding '{source} -> {destination}' oluşturma hatası: {e}")
            return False
            
    def set_policy(self, name: str, pattern: str, definition: Dict,
                  priority: int = 0, apply_to: str = "queues") -> bool:
        """Policy tanımla."""
        logger.info(f"Policy tanımlanıyor: {name}")
        
        payload = {
            "pattern": pattern,
            "definition": definition,
            "priority": priority,
            "apply-to": apply_to
        }
        
        try:
            response = requests.put(
                f"{self.base_url}/policies/{self.vhost_encoded}/{name}",
                auth=self.auth,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                logger.info(f"✓ Policy '{name}' başarıyla oluşturuldu")
                return True
            else:
                logger.error(f"✗ Policy '{name}' oluşturulamadı: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"✗ Policy '{name}' oluşturma hatası: {e}")
            return False
            
    def setup_topology(self) -> bool:
        """Task 6.1: Complete queue topology setup."""
        logger.info("=== Task 6.1: RabbitMQ Queue Topology Kurulumu ===")
        
        # 1. Jobs.direct exchange oluştur
        logger.info("--- Ana Jobs.direct Exchange oluşturuluyor ---")
        if not self.declare_exchange(JOBS_EXCHANGE, "direct", True):
            return False
            
        # 2. Per-queue dead letter exchanges oluştur
        logger.info("--- Per-Queue Dead Letter Exchange'ler oluşturuluyor ---")
        for queue_name in MAIN_QUEUES:
            dlx_name = f"{queue_name}{DLX_SUFFIX}"
            if not self.declare_exchange(dlx_name, "direct", True):
                return False
                
        # 3. Primary queues oluştur (quorum type)
        logger.info("--- Primary Queues oluşturuluyor (Quorum Type) ---")
        for queue_name in MAIN_QUEUES:
            config = QUEUE_CONFIGS[queue_name]
            dlx_name = f"{queue_name}{DLX_SUFFIX}"
            
            # Task 6.1: Quorum queue arguments
            queue_arguments = {
                # Dead letter configuration - her queue'nun kendi DLX'i
                "x-dead-letter-exchange": dlx_name,
                "x-dead-letter-routing-key": "#",  # Catch-all routing key
                # Message and queue limits
                "x-message-ttl": config["ttl"],
                "x-max-length-bytes": config["max_message_bytes"],  # 10MB limit
                "x-max-retries": config["max_retries"],
                # Priority configuration
                "x-max-priority": 10,
                "x-priority": config["priority"],
            }
            
            if not self.declare_queue(queue_name, True, "quorum", queue_arguments):
                return False
                
        # 4. Dead letter queues oluştur (classic lazy)
        logger.info("--- Dead Letter Queues oluşturuluyor (Classic Lazy) ---")
        for queue_name in MAIN_QUEUES:
            dlq_name = f"{queue_name}{DLQ_SUFFIX}"
            
            # Task 6.1: Classic lazy queue arguments for DLQs
            dlq_arguments = {
                "x-message-ttl": DLQ_CONFIG["ttl"],  # 24 hours
                "x-max-length": DLQ_CONFIG["max_length"],  # Max messages
                "x-queue-mode": DLQ_CONFIG["queue_mode"],  # Lazy mode
            }
            
            if not self.declare_queue(dlq_name, True, "classic", dlq_arguments):
                return False
                
        # 5. Primary queue bindings (jobs.direct -> queues)
        logger.info("--- Primary Queue Bindings oluşturuluyor ---")
        for queue_name in MAIN_QUEUES:
            # Bind primary queue to jobs.direct exchange with queue name as routing key
            if not self.create_binding(JOBS_EXCHANGE, queue_name, queue_name, "queue"):
                return False
                
        # 6. Dead letter queue bindings (DLX -> DLQs)  
        logger.info("--- Dead Letter Queue Bindings oluşturuluyor ---")
        for queue_name in MAIN_QUEUES:
            dlx_name = f"{queue_name}{DLX_SUFFIX}"
            dlq_name = f"{queue_name}{DLQ_SUFFIX}"
            
            # Bind DLQ to its DLX with catch-all routing key
            if not self.create_binding(dlx_name, dlq_name, "#", "queue"):
                return False
                
        # 7. Policies for message size limits and publisher confirms
        logger.info("--- Policies uygulanıyor ---")
        
        # Task 6.1: Message size limit policy (10MB)
        message_size_policy = {
            "max-message-bytes": 10485760,  # 10MB
            "confirm-publish": True,  # Publisher confirms
        }
        if not self.set_policy("message-size-limit", "^(default|model|cam|sim|report|erp)$", 
                              message_size_policy, 20, "queues"):
            return False
            
        # DLQ retention policy
        dlq_policy = {
            "message-ttl": DLQ_CONFIG["ttl"],
            "max-length": DLQ_CONFIG["max_length"],
            "expires": None,  # DLQs never expire
        }
        if not self.set_policy("dlq-retention", ".*_dlq$", dlq_policy, 15, "queues"):
            return False
            
        # High availability policy for quorum queues
        ha_policy = {
            "ha-mode": "all",
            "ha-sync-mode": "automatic",
        }
        if not self.set_policy("quorum-ha", "^(default|model|cam|sim|report|erp)$", 
                              ha_policy, 10, "queues"):
            return False
            
        logger.info("=== Task 6.1: Queue Topology Kurulumu Tamamlandı! ===")
        return True
        
    def verify_topology(self) -> bool:
        """Topology'nin doğru kurulduğunu doğrula."""
        logger.info("--- Topology Doğrulaması ---")
        
        try:
            # Exchanges kontrolü
            response = requests.get(f"{self.base_url}/exchanges/{self.vhost_encoded}",
                                  auth=self.auth, timeout=10)
            if response.status_code == 200:
                exchanges = response.json()
                exchange_names = [ex["name"] for ex in exchanges]
                
                # jobs.direct exchange kontrolü
                if JOBS_EXCHANGE not in exchange_names:
                    logger.error(f"✗ {JOBS_EXCHANGE} exchange bulunamadı!")
                    return False
                logger.info(f"✓ {JOBS_EXCHANGE} exchange bulundu")
                
                # DLX'ler kontrolü
                for queue_name in MAIN_QUEUES:
                    dlx_name = f"{queue_name}{DLX_SUFFIX}"
                    if dlx_name not in exchange_names:
                        logger.error(f"✗ DLX {dlx_name} bulunamadı!")
                        return False
                logger.info("✓ Tüm DLX'ler bulundu")
                
            # Queues kontrolü
            response = requests.get(f"{self.base_url}/queues/{self.vhost_encoded}",
                                  auth=self.auth, timeout=10)
            if response.status_code == 200:
                queues = response.json()
                queue_names = [q["name"] for q in queues]
                
                # Primary queues kontrolü
                for queue_name in MAIN_QUEUES:
                    if queue_name not in queue_names:
                        logger.error(f"✗ Primary queue {queue_name} bulunamadı!")
                        return False
                logger.info("✓ Tüm primary queue'lar bulundu")
                
                # DLQ'lar kontrolü
                for queue_name in MAIN_QUEUES:
                    dlq_name = f"{queue_name}{DLQ_SUFFIX}"
                    if dlq_name not in queue_names:
                        logger.error(f"✗ DLQ {dlq_name} bulunamadı!")
                        return False
                logger.info("✓ Tüm DLQ'lar bulundu")
                
            logger.info("✓ Topology doğrulaması başarılı!")
            return True
            
        except Exception as e:
            logger.error(f"✗ Topology doğrulaması başarısız: {e}")
            return False
            
    def print_summary(self):
        """Kurulum özetini yazdır."""
        logger.info("")
        logger.info("=== KURULUM ÖZETİ ===")
        logger.info("Konfigüre edilen topology:")
        logger.info("")
        logger.info(f"📋 Primary Exchange: {JOBS_EXCHANGE}")
        logger.info("📋 Primary Queues (Quorum):")
        for queue_name in MAIN_QUEUES:
            config = QUEUE_CONFIGS[queue_name]
            logger.info(f"  ✓ {queue_name} (TTL: {config['ttl']}ms, Priority: {config['priority']})")
            
        logger.info("")
        logger.info("📋 Dead Letter Topology:")
        for queue_name in MAIN_QUEUES:
            dlx_name = f"{queue_name}{DLX_SUFFIX}"
            dlq_name = f"{queue_name}{DLQ_SUFFIX}"
            logger.info(f"  ✓ {queue_name} -> {dlx_name} -> {dlq_name}")
            
        logger.info("")
        logger.info("📋 Routing Key Mappings:")
        for routing_key, queue_name in ROUTING_KEY_MAPPINGS.items():
            logger.info(f"  ✓ {routing_key} -> {queue_name}")
            
        logger.info("")
        logger.info(f"🌐 Management UI: http://{self.host}:{self.port}")
        logger.info(f"👤 Username: {self.username}")
        logger.info("")


def main():
    """Ana fonksiyon."""
    # Environment variables'dan ayarları al
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    rabbitmq_mgmt_port = int(os.getenv("RABBITMQ_MGMT_PORT", "15672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "freecad")
    rabbitmq_pass = os.getenv("RABBITMQ_PASS", "freecad")
    rabbitmq_vhost = os.getenv("RABBITMQ_VHOST", "/")
    
    # İnitializer oluştur
    initializer = RabbitMQInitializer(
        host=rabbitmq_host,
        port=rabbitmq_mgmt_port,
        username=rabbitmq_user,
        password=rabbitmq_pass,
        vhost=rabbitmq_vhost
    )
    
    try:
        # RabbitMQ'nun hazır olmasını bekle
        if not initializer.wait_for_rabbitmq():
            logger.error("RabbitMQ başlatılamadı, kurulum durduruldu")
            sys.exit(1)
            
        # Topology'i kur
        if not initializer.setup_topology():
            logger.error("Topology kurulumu başarısız")
            sys.exit(1)
            
        # Doğrula
        if not initializer.verify_topology():
            logger.error("Topology doğrulaması başarısız")
            sys.exit(1)
            
        # Özet yazdır
        initializer.print_summary()
        
        logger.info("🎉 Task 6.1 RabbitMQ topology kurulumu başarıyla tamamlandı!")
        
    except KeyboardInterrupt:
        logger.info("Kurulum kullanıcı tarafından durduruldu")
        sys.exit(130)
    except Exception as e:
        logger.error(f"Beklenmeyen hata: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()