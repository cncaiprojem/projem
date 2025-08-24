#!/usr/bin/env python3
"""
Task 6.7: Initialize RabbitMQ Event Exchanges
Creates the events.jobs topic exchange and ERP outbound bridge

This script sets up:
- events.jobs topic exchange for internal event routing
- erp.outbound fanout exchange for ERP bridge
- Exchange-to-exchange binding for job.status.* events
"""

import logging
import os
import sys
import time
from typing import Optional

import requests
from requests.auth import HTTPBasicAuth
import requests.exceptions

# Add API module to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class EventExchangeInitializer:
    """Initialize event exchanges for Task 6.7."""
    
    def __init__(self, host: str = "localhost", port: int = 15672,
                 username: str = "freecad", password: str = "freecad_dev_pass",
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
        """Wait for RabbitMQ to be ready."""
        logger.info("Waiting for RabbitMQ to be ready...")
        
        for attempt in range(1, max_attempts + 1):
            try:
                response = requests.get(
                    f"{self.base_url}/aliveness-test/{self.vhost_encoded}",
                    auth=self.auth,
                    timeout=5
                )
                if response.status_code == 200:
                    logger.info(f"✓ RabbitMQ ready! (Attempt: {attempt}/{max_attempts})")
                    return True
                    
            except requests.exceptions.RequestException as e:
                logger.debug(f"RabbitMQ connection error: {e}")
                
            logger.warning(f"RabbitMQ not ready yet, waiting... ({attempt}/{max_attempts})")
            time.sleep(2)
            
        logger.error(f"RabbitMQ not ready after {max_attempts} attempts!")
        return False
    
    def declare_exchange(self, name: str, exchange_type: str = "direct",
                        durable: bool = True) -> bool:
        """Create an exchange."""
        logger.info(f"Declaring exchange: {name} (type: {exchange_type})")
        
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
                logger.info(f"✓ Exchange '{name}' created successfully")
                return True
            else:
                logger.error(f"✗ Failed to create exchange '{name}': {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ Error creating exchange '{name}': {e}")
            return False
    
    def bind_exchanges(self, source: str, destination: str, routing_key: str = "") -> bool:
        """Bind one exchange to another (exchange-to-exchange binding)."""
        logger.info(f"Binding exchanges: {source} -> {destination} (routing_key: {routing_key})")
        
        payload = {
            "routing_key": routing_key,
            "arguments": {}
        }
        
        try:
            # Exchange-to-exchange binding uses 'e' for both source and destination
            response = requests.post(
                f"{self.base_url}/bindings/{self.vhost_encoded}/e/{source}/e/{destination}",
                auth=self.auth,
                headers={"Content-Type": "application/json"},
                json=payload,
                timeout=10
            )
            
            if response.status_code in [200, 201, 204]:
                logger.info(f"✓ Exchange binding '{source} -> {destination}' created successfully")
                return True
            else:
                logger.error(f"✗ Failed to bind exchanges: {response.status_code} - {response.text}")
                return False
                
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ Error binding exchanges: {e}")
            return False
    
    def setup_event_exchanges(self) -> bool:
        """Setup event exchanges for Task 6.7."""
        logger.info("=== Task 6.7: Event Exchange Setup ===")
        
        # 1. Create events.jobs topic exchange
        if not self.declare_exchange("events.jobs", "topic", True):
            return False
        
        # 2. Create erp.outbound fanout exchange
        if not self.declare_exchange("erp.outbound", "fanout", True):
            return False
        
        # 3. Bind ERP bridge to events exchange for job.status.* events
        # This creates the fanout pattern: events.jobs -> erp.outbound
        if not self.bind_exchanges("events.jobs", "erp.outbound", "job.status.#"):
            return False
        
        logger.info("=== Task 6.7: Event Exchange Setup Complete! ===")
        return True
    
    def verify_setup(self) -> bool:
        """Verify the exchanges are properly set up."""
        logger.info("--- Verifying Event Exchange Setup ---")
        
        try:
            # Check exchanges
            response = requests.get(
                f"{self.base_url}/exchanges/{self.vhost_encoded}",
                auth=self.auth,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"✗ Failed to fetch exchanges: HTTP {response.status_code}")
                return False
            
            exchanges = response.json()
            exchange_names = [ex["name"] for ex in exchanges]
            
            # Check events.jobs exchange
            if "events.jobs" not in exchange_names:
                logger.error("✗ events.jobs exchange not found!")
                return False
            logger.info("✓ events.jobs exchange found")
            
            # Check erp.outbound exchange
            if "erp.outbound" not in exchange_names:
                logger.error("✗ erp.outbound exchange not found!")
                return False
            logger.info("✓ erp.outbound exchange found")
            
            # Check bindings
            response = requests.get(
                f"{self.base_url}/bindings/{self.vhost_encoded}",
                auth=self.auth,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"✗ Failed to fetch bindings: HTTP {response.status_code}")
                return False
            
            bindings = response.json()
            
            # Look for exchange-to-exchange binding
            binding_found = False
            for binding in bindings:
                if (binding.get("source") == "events.jobs" and
                    binding.get("destination") == "erp.outbound" and
                    binding.get("destination_type") == "exchange"):
                    binding_found = True
                    break
            
            if not binding_found:
                logger.error("✗ Exchange binding events.jobs -> erp.outbound not found!")
                return False
            logger.info("✓ Exchange binding events.jobs -> erp.outbound found")
            
            logger.info("✓ Event exchange verification successful!")
            return True
            
        except requests.exceptions.RequestException as e:
            logger.error(f"✗ Event exchange verification failed: {e}")
            return False
    
    def print_summary(self):
        """Print setup summary."""
        logger.info("")
        logger.info("=== EVENT EXCHANGE SUMMARY ===")
        logger.info("")
        logger.info("📋 Topic Exchange: events.jobs")
        logger.info("   - Receives job.status.changed events")
        logger.info("   - Routes events based on routing keys")
        logger.info("")
        logger.info("📋 Fanout Exchange: erp.outbound")
        logger.info("   - Receives all job.status.* events from events.jobs")
        logger.info("   - Fans out to all bound ERP integration queues")
        logger.info("")
        logger.info("📋 Event Routing:")
        logger.info("   - job.status.changed -> events.jobs -> erp.outbound")
        logger.info("")
        logger.info(f"🌐 Management UI: http://{self.host}:{self.port}")
        logger.info(f"👤 Username: {self.username}")
        logger.info("")


def main():
    """Main function."""
    # Get settings from environment
    rabbitmq_host = os.getenv("RABBITMQ_HOST", "localhost")
    rabbitmq_mgmt_port = int(os.getenv("RABBITMQ_MGMT_PORT", "15672"))
    rabbitmq_user = os.getenv("RABBITMQ_USER", "freecad")
    rabbitmq_pass = os.getenv("RABBITMQ_PASS", "freecad_dev_pass")
    rabbitmq_vhost = os.getenv("RABBITMQ_VHOST", "/")
    
    # Create initializer
    initializer = EventExchangeInitializer(
        host=rabbitmq_host,
        port=rabbitmq_mgmt_port,
        username=rabbitmq_user,
        password=rabbitmq_pass,
        vhost=rabbitmq_vhost
    )
    
    try:
        # Wait for RabbitMQ
        if not initializer.wait_for_rabbitmq():
            logger.error("RabbitMQ not available, setup aborted")
            sys.exit(1)
        
        # Setup exchanges
        if not initializer.setup_event_exchanges():
            logger.error("Event exchange setup failed")
            sys.exit(1)
        
        # Verify setup
        if not initializer.verify_setup():
            logger.error("Event exchange verification failed")
            sys.exit(1)
        
        # Print summary
        initializer.print_summary()
        
        logger.info("🎉 Task 6.7 Event Exchange setup completed successfully!")
        
    except KeyboardInterrupt:
        logger.info("Setup interrupted by user")
        sys.exit(130)
    except requests.exceptions.RequestException as e:
        logger.error(f"RabbitMQ API error: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()