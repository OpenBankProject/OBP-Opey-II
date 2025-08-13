#!/usr/bin/env python3
"""
CORS Testing Script for Opey II

This script tests CORS configuration by making requests from different origins
and checking the response headers.
"""

import asyncio
import aiohttp
import argparse
import json
import sys
from typing import Dict, List, Optional


class CORSTestResult:
    def __init__(self, test_name: str, success: bool, details: str):
        self.test_name = test_name
        self.success = success
        self.details = details

    def __str__(self):
        status = "✅ PASS" if self.success else "❌ FAIL"
        return f"{status} {self.test_name}: {self.details}"


class CORSTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip('/')
        self.results: List[CORSTestResult] = []

    async def test_preflight_request(self, origin: str, endpoint: str = "/stream") -> CORSTestResult:
        """Test CORS preflight (OPTIONS) request"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,Authorization,Consent-JWT"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.options(url, headers=headers) as response:
                    # Check response status
                    if response.status != 200:
                        return CORSTestResult(
                            f"Preflight from {origin}",
                            False,
                            f"Status {response.status}, expected 200"
                        )

                    # Check required CORS headers
                    cors_origin = response.headers.get('Access-Control-Allow-Origin')
                    cors_methods = response.headers.get('Access-Control-Allow-Methods')
                    cors_headers = response.headers.get('Access-Control-Allow-Headers')
                    cors_credentials = response.headers.get('Access-Control-Allow-Credentials')

                    issues = []
                    if not cors_origin:
                        issues.append("Missing Access-Control-Allow-Origin")
                    elif cors_origin != origin and cors_origin != "*":
                        issues.append(f"Wrong origin: got {cors_origin}, expected {origin}")

                    if not cors_methods:
                        issues.append("Missing Access-Control-Allow-Methods")
                    elif "POST" not in cors_methods.upper():
                        issues.append("POST method not allowed")

                    if not cors_headers:
                        issues.append("Missing Access-Control-Allow-Headers")

                    if cors_credentials != "true":
                        issues.append("Credentials not allowed")

                    if issues:
                        return CORSTestResult(
                            f"Preflight from {origin}",
                            False,
                            "; ".join(issues)
                        )

                    return CORSTestResult(
                        f"Preflight from {origin}",
                        True,
                        f"All headers present - Origin: {cors_origin}, Methods: {cors_methods}"
                    )

        except Exception as e:
            return CORSTestResult(
                f"Preflight from {origin}",
                False,
                f"Request failed: {str(e)}"
            )

    async def test_actual_request(self, origin: str, endpoint: str = "/status") -> CORSTestResult:
        """Test actual CORS request"""
        url = f"{self.base_url}{endpoint}"
        headers = {
            "Origin": origin,
            "Content-Type": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    # Check CORS headers in response
                    cors_origin = response.headers.get('Access-Control-Allow-Origin')
                    cors_credentials = response.headers.get('Access-Control-Allow-Credentials')

                    issues = []
                    if not cors_origin:
                        issues.append("Missing Access-Control-Allow-Origin in response")
                    elif cors_origin != origin and cors_origin != "*":
                        issues.append(f"Wrong origin in response: got {cors_origin}, expected {origin}")

                    if cors_credentials != "true":
                        issues.append("Credentials not allowed in response")

                    # Note: We might get 401 due to missing session, but CORS headers should still be present
                    if issues:
                        return CORSTestResult(
                            f"Actual request from {origin}",
                            False,
                            "; ".join(issues)
                        )

                    return CORSTestResult(
                        f"Actual request from {origin}",
                        True,
                        f"CORS headers present - Status: {response.status}, Origin: {cors_origin}"
                    )

        except Exception as e:
            return CORSTestResult(
                f"Actual request from {origin}",
                False,
                f"Request failed: {str(e)}"
            )

    async def test_forbidden_origin(self, forbidden_origin: str) -> CORSTestResult:
        """Test that forbidden origins are rejected"""
        url = f"{self.base_url}/status"
        headers = {
            "Origin": forbidden_origin,
            "Access-Control-Request-Method": "GET"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.options(url, headers=headers) as response:
                    cors_origin = response.headers.get('Access-Control-Allow-Origin')
                    
                    # Should either not have the header or not match the origin
                    if cors_origin == forbidden_origin:
                        return CORSTestResult(
                            f"Forbidden origin {forbidden_origin}",
                            False,
                            f"Forbidden origin was allowed: {cors_origin}"
                        )

                    return CORSTestResult(
                        f"Forbidden origin {forbidden_origin}",
                        True,
                        f"Correctly rejected - CORS origin: {cors_origin or 'None'}"
                    )

        except Exception as e:
            return CORSTestResult(
                f"Forbidden origin {forbidden_origin}",
                False,
                f"Request failed: {str(e)}"
            )

    async def run_all_tests(self, test_origins: Optional[List[str]] = None) -> Dict:
        """Run all CORS tests"""
        if test_origins is None:
            test_origins = [
                "http://localhost:5174",
                "http://localhost:3000", 
                "http://127.0.0.1:5174"
            ]

        forbidden_origins = [
            "http://malicious-site.com",
            "https://evil.example.com"
        ]

        print(f"🧪 Testing CORS configuration for {self.base_url}")
        print(f"🎯 Testing {len(test_origins)} allowed origins")
        print(f"🚫 Testing {len(forbidden_origins)} forbidden origins")
        print("-" * 60)

        # Test preflight requests for allowed origins
        for origin in test_origins:
            result = await self.test_preflight_request(origin)
            self.results.append(result)
            print(result)

        # Test actual requests for allowed origins  
        for origin in test_origins:
            result = await self.test_actual_request(origin)
            self.results.append(result)
            print(result)

        # Test forbidden origins
        for origin in forbidden_origins:
            result = await self.test_forbidden_origin(origin)
            self.results.append(result)
            print(result)

        # Summary
        passed = sum(1 for r in self.results if r.success)
        total = len(self.results)
        
        print("-" * 60)
        print(f"📊 Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All CORS tests passed!")
            return {"status": "success", "passed": passed, "total": total}
        else:
            print("⚠️  Some CORS tests failed. Check configuration.")
            failed_tests = [r for r in self.results if not r.success]
            print("\nFailed tests:")
            for test in failed_tests:
                print(f"  - {test}")
            return {"status": "failure", "passed": passed, "total": total, "failures": failed_tests}


async def main():
    parser = argparse.ArgumentParser(description="Test CORS configuration for Opey II")
    parser.add_argument(
        "--url", 
        default="http://localhost:8000", 
        help="Base URL of the Opey II service (default: http://localhost:8000)"
    )
    parser.add_argument(
        "--origins", 
        nargs="+", 
        help="Origins to test (default: common development origins)"
    )
    parser.add_argument(
        "--json", 
        action="store_true", 
        help="Output results in JSON format"
    )

    args = parser.parse_args()

    tester = CORSTester(args.url)
    
    try:
        results = await tester.run_all_tests(args.origins)
        
        if args.json:
            print(json.dumps(results, indent=2))
        
        # Exit with appropriate code
        sys.exit(0 if results["status"] == "success" else 1)
        
    except KeyboardInterrupt:
        print("\n🛑 Testing interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())