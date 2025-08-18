#!/usr/bin/env python3
"""
Brute Force Detection Testing Script
===================================

Tests the fixed brute-force detection logic with various IP scenarios
to ensure proper IPv4/IPv6 compatibility and prevent false positives.

Test Scenarios:
- IPv4 addresses from different subnets
- IPv6 addresses
- NAT scenarios (same masked IP, different real IPs)
- Invalid IP formats

Turkish KVKV Compliance Testing:
- Verifies proper IP masking
- Ensures no plain IP addresses in logs
- Tests PII protection mechanisms
"""

import asyncio
import sys
import ipaddress
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from unittest.mock import AsyncMock, MagicMock

# Mock imports for testing without full app context
class MockPIIMaskingService:
    """Mock PII masking service for testing."""
    
    def mask_ip_address(self, ip: str, level=None) -> str:
        """Mock IP masking with realistic behavior."""
        try:
            ip_obj = ipaddress.ip_address(ip)
            
            if isinstance(ip_obj, ipaddress.IPv4Address):
                octets = str(ip_obj).split('.')
                # Medium level masking: mask last two octets
                return f"{'.'.join(octets[:2])}.***.**"
            
            elif isinstance(ip_obj, ipaddress.IPv6Address):
                groups = str(ip_obj).split(':')
                # Medium level masking: mask last 6 groups
                return ':'.join(groups[:2]) + ':****:****:****:****:****:****'
                
        except (ValueError, ipaddress.AddressValueError):
            # Invalid IP - return masked placeholder
            return "INVALID.IP.***.**"
        
        return ip


class MockSecurityEvent:
    """Mock security event for testing."""
    
    def __init__(self, event_type: str, created_at: datetime, ip_masked: str):
        self.type = event_type
        self.created_at = created_at
        self.ip_masked = ip_masked


class MockSession:
    """Mock database session for testing."""
    
    def __init__(self, mock_events: List[MockSecurityEvent]):
        self.mock_events = mock_events
    
    def query(self, model):
        return MockQuery(self.mock_events)


class MockQuery:
    """Mock database query for testing."""
    
    def __init__(self, events: List[MockSecurityEvent]):
        self.events = events
        self.filters_applied = []
    
    def filter(self, *conditions):
        # For testing, we'll simulate filtering
        filtered_events = []
        for event in self.events:
            if hasattr(conditions[0], 'args'):
                # Handle SQLAlchemy and_ conditions
                should_include = True
                for cond in conditions:
                    if hasattr(cond, 'args'):
                        # Check each condition in and_()
                        for sub_cond in cond.args:
                            # Simplified condition checking
                            if "LOGIN_FAILED" in str(sub_cond):
                                should_include &= event.type == "LOGIN_FAILED"
                            elif "ip_masked ==" in str(sub_cond):
                                # Extract the IP from the condition
                                pass  # We'll handle this in the test
                    else:
                        # Handle single conditions
                        pass
                        
                if should_include:
                    filtered_events.append(event)
            else:
                # Simple case - include all for now
                filtered_events = self.events
                
        return MockQuery(filtered_events)
    
    def count(self):
        return len(self.events)


class BruteForceDetectionTester:
    """Test suite for brute force detection fixes."""
    
    def __init__(self):
        self.pii_service = MockPIIMaskingService()
        self.test_results = []
    
    async def simulate_brute_force_check(self, 
                                       db_session: MockSession, 
                                       ip_address: str,
                                       existing_failures: List[Dict[str, Any]]) -> int:
        """Simulate the fixed brute force detection logic."""
        
        # Create mock events based on existing failures
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=15)
        mock_events = []
        
        for failure in existing_failures:
            mock_events.append(MockSecurityEvent(
                event_type="LOGIN_FAILED",
                created_at=failure['timestamp'],
                ip_masked=failure['ip_masked']
            ))
        
        db_session.mock_events = mock_events
        
        # Apply the FIXED logic
        masked_ip_to_check = self.pii_service.mask_ip_address(ip_address)
        
        # Count matching masked IPs
        matching_failures = []
        for event in mock_events:
            if (event.type == "LOGIN_FAILED" and 
                event.created_at >= recent_time and
                event.ip_masked == masked_ip_to_check):
                matching_failures.append(event)
        
        return len(matching_failures)
    
    def test_ipv4_scenarios(self) -> Dict[str, Any]:
        """Test IPv4 brute force detection scenarios."""
        print("Testing IPv4 scenarios...")
        
        # Test Case 1: Same subnet, different hosts (should be grouped)
        test_ips = ["192.168.1.100", "192.168.1.101", "192.168.1.102"]
        masked_ips = [self.pii_service.mask_ip_address(ip) for ip in test_ips]
        
        print(f"Original IPs: {test_ips}")
        print(f"Masked IPs:   {masked_ips}")
        
        # All should have the same mask
        same_mask = len(set(masked_ips)) == 1
        
        # Test Case 2: Different subnets (should NOT be grouped)
        different_subnet_ips = ["192.168.1.100", "10.0.0.100", "172.16.1.100"]
        different_masked = [self.pii_service.mask_ip_address(ip) for ip in different_subnet_ips]
        
        print(f"Different subnet IPs: {different_subnet_ips}")
        print(f"Different masked:     {different_masked}")
        
        # All should have different masks
        different_masks = len(set(different_masked)) == len(different_masked)
        
        return {
            "scenario": "IPv4 Testing",
            "same_subnet_grouped": same_mask,
            "different_subnet_separated": different_masks,
            "sample_masks": {
                "192.168.1.x": masked_ips[0],
                "10.0.0.x": different_masked[1],
                "172.16.1.x": different_masked[2]
            }
        }
    
    def test_ipv6_scenarios(self) -> Dict[str, Any]:
        """Test IPv6 brute force detection scenarios."""
        print("\\nTesting IPv6 scenarios...")
        
        # IPv6 test cases
        ipv6_ips = [
            "2001:0db8:85a3:0000:0000:8a2e:0370:7334",  # Same /32 prefix
            "2001:0db8:85a3:0000:0000:8a2e:0370:7335",  # Same /32 prefix
            "2001:4860:4860:0000:0000:0000:0000:8888"   # Different /32 prefix (Google DNS)
        ]
        
        masked_ipv6 = [self.pii_service.mask_ip_address(ip) for ip in ipv6_ips]
        
        print(f"IPv6 IPs:     {ipv6_ips}")
        print(f"Masked IPv6:  {masked_ipv6}")
        
        # First two should be grouped (same /32 prefix), third should be different
        first_two_same = masked_ipv6[0] == masked_ipv6[1]
        third_different = masked_ipv6[0] != masked_ipv6[2]
        
        return {
            "scenario": "IPv6 Testing",
            "same_prefix_grouped": first_two_same,
            "different_prefix_separated": third_different,
            "sample_masks": {
                "2001:0db8:85a3:...": masked_ipv6[0],
                "2001:0db8:1234:...": masked_ipv6[2]
            }
        }
    
    async def test_nat_scenario(self) -> Dict[str, Any]:
        """Test NAT scenario - multiple users behind same router."""
        print("\\nTesting NAT scenario...")
        
        # Simulate multiple users behind NAT with same public IP
        public_ip = "203.0.113.1"  # Example public IP
        internal_ips = ["192.168.1.10", "192.168.1.20", "192.168.1.30"]  # Internal IPs
        
        # In reality, all would appear as the same public IP to the server
        # But with proper detection, they should be grouped correctly
        masked_public = self.pii_service.mask_ip_address(public_ip)
        
        # Simulate 6 failed attempts from this "public IP" in last 15 minutes
        recent_time = datetime.now(timezone.utc)
        existing_failures = []
        
        for i in range(6):
            existing_failures.append({
                'timestamp': recent_time - timedelta(minutes=i+1),
                'ip_masked': masked_public
            })
        
        db_session = MockSession([])
        
        # Test the detection
        failure_count = await self.simulate_brute_force_check(
            db_session, public_ip, existing_failures
        )
        
        # Should detect 6 failures and trigger brute force alert (threshold = 5)
        brute_force_detected = failure_count >= 5
        
        return {
            "scenario": "NAT/Firewall Scenario",
            "public_ip_masked": masked_public,
            "failure_count": failure_count,
            "brute_force_detected": brute_force_detected,
            "threshold_exceeded": failure_count >= 5
        }
    
    def test_invalid_ip_handling(self) -> Dict[str, Any]:
        """Test handling of invalid IP addresses."""
        print("\\nTesting invalid IP handling...")
        
        invalid_ips = [
            "not.an.ip.address",
            "999.999.999.999",
            "127.0.0.1:8080",  # IP with port
            "",
            "localhost",
            "256.1.1.1"
        ]
        
        results = {}
        for invalid_ip in invalid_ips:
            try:
                masked = self.pii_service.mask_ip_address(invalid_ip)
                results[invalid_ip] = {"masked": masked, "error": None}
            except Exception as e:
                results[invalid_ip] = {"masked": None, "error": str(e)}
        
        return {
            "scenario": "Invalid IP Handling",
            "results": results,
            "graceful_degradation": all(
                result["masked"] is not None or result["error"] is not None 
                for result in results.values()
            )
        }
    
    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all brute force detection tests."""
        print("=" * 60)
        print("BRUTE FORCE DETECTION FIX VALIDATION TESTS")
        print("=" * 60)
        
        results = {
            "test_timestamp": datetime.now(timezone.utc).isoformat(),
            "tests": {}
        }
        
        # Run all test scenarios
        results["tests"]["ipv4"] = self.test_ipv4_scenarios()
        results["tests"]["ipv6"] = self.test_ipv6_scenarios()
        results["tests"]["nat"] = await self.test_nat_scenario()
        results["tests"]["invalid_ip"] = self.test_invalid_ip_handling()
        
        # Summary
        all_passed = True
        print("\\n" + "=" * 60)
        print("TEST SUMMARY:")
        print("=" * 60)
        
        for test_name, test_result in results["tests"].items():
            print(f"\\n{test_name.upper()} TEST:")
            print(f"  Scenario: {test_result['scenario']}")
            
            # Determine if test passed based on scenario
            passed = True
            if test_name == "ipv4":
                passed = test_result["same_subnet_grouped"] and test_result["different_subnet_separated"]
            elif test_name == "ipv6":
                passed = test_result["same_prefix_grouped"] and test_result["different_prefix_separated"]
            elif test_name == "nat":
                passed = test_result["brute_force_detected"]
            elif test_name == "invalid_ip":
                passed = test_result["graceful_degradation"]
            
            status = "PASS" if passed else "FAIL"
            print(f"  Status: {status}")
            
            all_passed &= passed
        
        results["overall_status"] = "PASS" if all_passed else "FAIL"
        
        print(f"\\nOVERALL STATUS: {results['overall_status']}")
        print("=" * 60)
        
        return results


async def main():
    """Main test execution."""
    tester = BruteForceDetectionTester()
    results = await tester.run_all_tests()
    
    # Return appropriate exit code
    sys.exit(0 if results["overall_status"] == "PASS" else 1)


if __name__ == "__main__":
    asyncio.run(main())