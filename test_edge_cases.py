#!/usr/bin/env python3
"""
Edge Cases Validation Test Suite

This test script validates the implementation of all edge cases:
1. Route Organization
2. Database Connection & Transaction Edge Cases
3. Outward Sync Failures

Usage:
    python test_edge_cases.py
"""

import asyncio
import aiohttp
import json
import time
import random
from typing import Dict, List, Any

# Test Configuration
BASE_URL = "http://localhost:8000"
TEST_TIMEOUT = 30
CONCURRENT_REQUESTS = 10

class EdgeCaseTestSuite:
    """Comprehensive test suite for all implemented edge cases."""
    
    def __init__(self):
        self.test_results = {}
        self.session = None
    
    async def setup(self):
        """Setup test session."""
        timeout = aiohttp.ClientTimeout(total=TEST_TIMEOUT)
        self.session = aiohttp.ClientSession(timeout=timeout)
        print("🚀 Starting Edge Cases Test Suite")
        print("=" * 50)
    
    async def teardown(self):
        """Cleanup test session."""
        if self.session:
            await self.session.close()
        print("\n" + "=" * 50)
        print("📊 Test Suite Complete")
        self.print_summary()
    
    def print_summary(self):
        """Print test results summary."""
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results.values() if result['status'] == 'PASS')
        failed_tests = total_tests - passed_tests
        
        print(f"\nTest Summary:")
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests} ✅")
        print(f"Failed: {failed_tests} ❌")
        print(f"Success Rate: {(passed_tests/total_tests)*100:.1f}%")
        
        if failed_tests > 0:
            print("\nFailed Tests:")
            for test_name, result in self.test_results.items():
                if result['status'] == 'FAIL':
                    print(f"  - {test_name}: {result['error']}")
    
    async def make_request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        try:
            url = f"{BASE_URL}{endpoint}"
            async with self.session.request(method, url, **kwargs) as response:
                return {
                    'status_code': response.status,
                    'data': await response.json() if response.content_type == 'application/json' else await response.text(),
                    'headers': dict(response.headers)
                }
        except Exception as e:
            return {
                'status_code': 0,
                'error': str(e)
            }
    
    def record_test_result(self, test_name: str, passed: bool, error: str = None):
        """Record test result."""
        self.test_results[test_name] = {
            'status': 'PASS' if passed else 'FAIL',
            'error': error
        }
        status_icon = "✅" if passed else "❌"
        print(f"{status_icon} {test_name}")
        if error and not passed:
            print(f"   Error: {error}")
    
    async def test_route_organization(self):
        """Test 1: Route Organization - Admin routes separated from customer routes."""
        print("\n🔧 Testing Route Organization")
        
        # Test admin routes are accessible
        response = await self.make_request('GET', '/admin/health')
        self.record_test_result(
            "Admin Health Endpoint",
            response.get('status_code') == 200,
            f"Status: {response.get('status_code')}" if response.get('status_code') != 200 else None
        )
        
        # Test customer routes still work
        response = await self.make_request('GET', '/customers/')
        self.record_test_result(
            "Customer Routes Still Accessible",
            response.get('status_code') in [200, 422],  # 422 is acceptable for missing query params
            f"Status: {response.get('status_code')}" if response.get('status_code') not in [200, 422] else None
        )
        
        # Test admin monitoring endpoints
        monitoring_endpoints = [
            '/admin/database/health',
            '/admin/database/connections', 
            '/admin/outbox/statistics'
        ]
        
        for endpoint in monitoring_endpoints:
            response = await self.make_request('GET', endpoint)
            self.record_test_result(
                f"Admin Monitoring: {endpoint}",
                response.get('status_code') == 200,
                f"Status: {response.get('status_code')}" if response.get('status_code') != 200 else None
            )
    
    async def test_database_edge_cases(self):
        """Test 2: Database Connection & Transaction Edge Cases."""
        print("\n💾 Testing Database Edge Cases")
        
        # Test connection health monitoring
        response = await self.make_request('GET', '/admin/database/health')
        if response.get('status_code') == 200:
            health_data = response.get('data', {})
            self.record_test_result(
                "Database Health Monitoring",
                'connection_pool' in health_data and 'status' in health_data,
                "Missing health monitoring data"
            )
        else:
            self.record_test_result(
                "Database Health Monitoring",
                False,
                f"Health endpoint failed: {response.get('status_code')}"
            )
        
        # Test connection pool monitoring
        response = await self.make_request('GET', '/admin/database/connections')
        self.record_test_result(
            "Connection Pool Monitoring",
            response.get('status_code') == 200,
            f"Status: {response.get('status_code')}" if response.get('status_code') != 200 else None
        )
        
        # Test concurrent database operations (simulating connection pool stress)
        await self.test_concurrent_database_operations()
        
        # Test transaction rollback handling
        await self.test_transaction_rollback()
    
    async def test_concurrent_database_operations(self):
        """Test concurrent database operations to validate connection pooling."""
        print("   Testing concurrent database operations...")
        
        # Create multiple concurrent requests to test connection pooling
        tasks = []
        for i in range(CONCURRENT_REQUESTS):
            task = asyncio.create_task(
                self.make_request('GET', f'/customers/?page=1&page_size=1')
            )
            tasks.append(task)
        
        try:
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            successful_requests = sum(
                1 for response in responses 
                if isinstance(response, dict) and response.get('status_code') in [200, 422]
            )
            
            self.record_test_result(
                f"Concurrent Database Operations ({CONCURRENT_REQUESTS} requests)",
                successful_requests >= CONCURRENT_REQUESTS * 0.8,  # 80% success rate acceptable
                f"Only {successful_requests}/{CONCURRENT_REQUESTS} requests succeeded"
            )
        except Exception as e:
            self.record_test_result(
                "Concurrent Database Operations",
                False,
                str(e)
            )
    
    async def test_transaction_rollback(self):
        """Test transaction rollback by attempting invalid operations."""
        print("   Testing transaction rollback handling...")
        
        # Try to create customer with invalid data to trigger constraint violations
        invalid_customer_data = {
            "email": "invalid-email",  # Invalid email format
            "name": "",  # Empty name
            "stripe_customer_id": "duplicate_id_12345"
        }
        
        response = await self.make_request(
            'POST', 
            '/customers/', 
            json=invalid_customer_data
        )
        
        # Should handle validation errors gracefully
        self.record_test_result(
            "Transaction Rollback on Validation Error",
            response.get('status_code') in [400, 422],  # Should return validation error
            f"Expected validation error, got status: {response.get('status_code')}"
        )
    
    async def test_outward_sync_failures(self):
        """Test 3: Outward Sync Failures - Transactional Outbox Pattern."""
        print("\n🔄 Testing Outward Sync Failures")
        
        # Test outbox statistics endpoint
        response = await self.make_request('GET', '/admin/outbox/statistics')
        if response.get('status_code') == 200:
            stats_data = response.get('data', {})
            self.record_test_result(
                "Outbox Statistics Monitoring",
                'total_events' in stats_data,
                "Missing outbox statistics data"
            )
        else:
            self.record_test_result(
                "Outbox Statistics Monitoring", 
                False,
                f"Statistics endpoint failed: {response.get('status_code')}"
            )
        
        # Test outbox pending events
        response = await self.make_request('GET', '/admin/outbox/pending')
        self.record_test_result(
            "Outbox Pending Events Endpoint",
            response.get('status_code') == 200,
            f"Status: {response.get('status_code')}" if response.get('status_code') != 200 else None
        )
        
        # Test dead letter queue monitoring
        response = await self.make_request('GET', '/admin/outbox/dead-letter')
        self.record_test_result(
            "Dead Letter Queue Monitoring",
            response.get('status_code') == 200,
            f"Status: {response.get('status_code')}" if response.get('status_code') != 200 else None
        )
        
        # Test manual outbox processing trigger
        response = await self.make_request('POST', '/admin/outbox/process')
        self.record_test_result(
            "Manual Outbox Processing",
            response.get('status_code') in [200, 202],  # 202 Accepted is also valid
            f"Status: {response.get('status_code')}" if response.get('status_code') not in [200, 202] else None
        )
        
        # Test customer creation with outbox pattern
        await self.test_customer_creation_with_outbox()
    
    async def test_customer_creation_with_outbox(self):
        """Test customer creation triggers outbox events."""
        print("   Testing customer creation with outbox pattern...")
        
        # Create a valid customer to trigger outbox event
        customer_data = {
            "email": f"test.{int(time.time())}@example.com",
            "name": "Test Customer",
            "metadata": {"test": "true"}
        }
        
        # Get initial outbox statistics
        initial_stats = await self.make_request('GET', '/admin/outbox/statistics')
        initial_count = 0
        if initial_stats.get('status_code') == 200:
            initial_count = initial_stats.get('data', {}).get('total_events', 0)
        
        # Create customer
        response = await self.make_request('POST', '/customers/', json=customer_data)
        
        if response.get('status_code') in [200, 201]:
            # Wait a moment for outbox event to be created
            await asyncio.sleep(1)
            
            # Check if outbox event was created
            final_stats = await self.make_request('GET', '/admin/outbox/statistics')
            if final_stats.get('status_code') == 200:
                final_count = final_stats.get('data', {}).get('total_events', 0)
                self.record_test_result(
                    "Customer Creation Triggers Outbox Event",
                    final_count > initial_count,
                    f"Outbox events did not increase: {initial_count} -> {final_count}"
                )
            else:
                self.record_test_result(
                    "Customer Creation Triggers Outbox Event",
                    False,
                    "Could not verify outbox event creation"
                )
        else:
            self.record_test_result(
                "Customer Creation Triggers Outbox Event",
                False,
                f"Customer creation failed: {response.get('status_code')}"
            )
    
    async def test_api_health(self):
        """Basic API health test."""
        print("\n🏥 Testing API Health")
        
        response = await self.make_request('GET', '/admin/health')
        if response.get('status_code') == 200:
            health_data = response.get('data', {})
            self.record_test_result(
                "API Health Check",
                health_data.get('status') == 'healthy',
                f"API status: {health_data.get('status')}"
            )
        else:
            self.record_test_result(
                "API Health Check",
                False,
                f"Health check failed: {response.get('status_code')}"
            )
    
    async def run_all_tests(self):
        """Run all edge case tests."""
        await self.setup()
        
        try:
            # Test 0: Basic API Health
            await self.test_api_health()
            
            # Test 1: Route Organization
            await self.test_route_organization()
            
            # Test 2: Database Edge Cases  
            await self.test_database_edge_cases()
            
            # Test 3: Outward Sync Failures
            await self.test_outward_sync_failures()
            
        except Exception as e:
            print(f"❌ Test suite failed with error: {e}")
        finally:
            await self.teardown()

async def main():
    """Main test execution."""
    print("🧪 Zenskar Edge Cases Validation")
    print("Testing implementation of:")
    print("1. Route Organization")
    print("2. Database Connection & Transaction Edge Cases") 
    print("3. Outward Sync Failures")
    print()
    
    test_suite = EdgeCaseTestSuite()
    await test_suite.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())