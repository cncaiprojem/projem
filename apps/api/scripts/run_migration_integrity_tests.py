#!/usr/bin/env python3
"""
Migration and Integrity Test Runner - Task 2.9

Comprehensive test runner for migration safety, database integrity,
audit chain security, and performance validation with banking-level precision.

Usage:
    python scripts/run_migration_integrity_tests.py [OPTIONS]

Options:
    --suite SUITE       Test suite to run (all, migration, constraints, audit, performance)
    --verbose          Enable verbose output
    --report           Generate detailed test report
    --compliance       Run Turkish compliance-specific tests
    --performance      Run performance benchmarks
    --safety-check     Run pre-migration safety checks
    --help             Show this help message
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pytest


class MigrationTestRunner:
    """Comprehensive test runner for migration and integrity testing."""

    def __init__(self, verbose: bool = False, generate_report: bool = False):
        """Initialize test runner."""
        self.verbose = verbose
        self.generate_report = generate_report
        self.start_time = time.time()
        self.results: Dict[str, any] = {}

        # Determine paths
        self.script_dir = Path(__file__).parent
        self.api_dir = self.script_dir.parent
        self.test_dir = self.api_dir / "tests"
        self.report_dir = self.api_dir / "test_reports"

        # Ensure report directory exists
        self.report_dir.mkdir(exist_ok=True)

    def print_banner(self):
        """Print test runner banner."""
        print("=" * 80)
        print("🏗️  MIGRATION AND INTEGRITY TEST SUITE - TASK 2.9")
        print("   Ultra Enterprise Banking-Level Precision Testing")
        print("   FreeCAD CNC/CAM/CAD Production Platform")
        print("=" * 80)
        print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📁 Test Directory: {self.test_dir}")
        print(f"📊 Report Directory: {self.report_dir}")
        print()

    def run_migration_safety_tests(self) -> bool:
        """Run migration safety tests."""
        print("🔍 PHASE 1: Migration Safety Tests")
        print("   Testing Alembic upgrade/downgrade cycles...")

        test_args = [
            str(self.test_dir / "integration" / "test_migration_integrity.py::TestMigrationSafety"),
            "-v" if self.verbose else "-q",
            "--tb=short",
            "-m",
            "migration_safety",
        ]

        if self.generate_report:
            test_args.extend(
                [
                    "--junitxml",
                    str(self.report_dir / "migration_safety_report.xml"),
                    "--cov=app",
                    "--cov-report=xml:test_reports/migration_safety_coverage.xml",
                ]
            )

        result = pytest.main(test_args)
        success = result == 0

        self.results["migration_safety"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Migration safety tests PASSED")
        else:
            print("   ❌ Migration safety tests FAILED")

        print()
        return success

    def run_constraint_validation_tests(self) -> bool:
        """Run database constraint validation tests."""
        print("🔒 PHASE 2: Database Constraint Validation Tests")
        print("   Testing unique constraints, FK behavior, check constraints...")

        test_args = [
            str(
                self.test_dir
                / "integration"
                / "test_migration_integrity.py::TestDatabaseConstraints"
            ),
            "-v" if self.verbose else "-q",
            "--tb=short",
            "-m",
            "constraint_validation",
        ]

        if self.generate_report:
            test_args.extend(
                [
                    "--junitxml",
                    str(self.report_dir / "constraint_validation_report.xml"),
                    "--cov=app.models",
                    "--cov-report=xml:test_reports/constraint_validation_coverage.xml",
                ]
            )

        result = pytest.main(test_args)
        success = result == 0

        self.results["constraint_validation"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Constraint validation tests PASSED")
        else:
            print("   ❌ Constraint validation tests FAILED")

        print()
        return success

    def run_audit_integrity_tests(self) -> bool:
        """Run audit chain integrity tests."""
        print("🔐 PHASE 3: Audit Chain Integrity Tests")
        print("   Testing cryptographic hash chains and Turkish compliance...")

        test_args = [
            str(
                self.test_dir
                / "integration"
                / "test_migration_integrity.py::TestAuditChainIntegrity"
            ),
            "-v" if self.verbose else "-q",
            "--tb=short",
            "-m",
            "audit_integrity",
        ]

        if self.generate_report:
            test_args.extend(
                [
                    "--junitxml",
                    str(self.report_dir / "audit_integrity_report.xml"),
                    "--cov=app.models.audit_log",
                    "--cov-report=xml:test_reports/audit_integrity_coverage.xml",
                ]
            )

        result = pytest.main(test_args)
        success = result == 0

        self.results["audit_integrity"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Audit integrity tests PASSED")
        else:
            print("   ❌ Audit integrity tests FAILED")

        print()
        return success

    def run_performance_tests(self) -> bool:
        """Run query performance and index usage tests."""
        print("⚡ PHASE 4: Query Performance Tests")
        print("   Testing index usage and performance benchmarks...")

        test_args = [
            str(
                self.test_dir / "integration" / "test_migration_integrity.py::TestQueryPerformance"
            ),
            "-v" if self.verbose else "-q",
            "--tb=short",
            "-m",
            "performance_validation",
        ]

        if self.generate_report:
            test_args.extend(
                ["--junitxml", str(self.report_dir / "performance_validation_report.xml")]
            )

        result = pytest.main(test_args)
        success = result == 0

        self.results["performance_validation"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Performance validation tests PASSED")
        else:
            print("   ❌ Performance validation tests FAILED")

        print()
        return success

    def run_integration_tests(self) -> bool:
        """Run complete integration tests."""
        print("🏗️  PHASE 5: Complete Integration Tests")
        print("   Testing complete migration integrity workflow...")

        test_args = [
            str(
                self.test_dir
                / "integration"
                / "test_migration_integrity.py::TestMigrationIntegrityIntegration"
            ),
            "-v" if self.verbose else "-q",
            "--tb=short",
        ]

        if self.generate_report:
            test_args.extend(
                [
                    "--junitxml",
                    str(self.report_dir / "integration_tests_report.xml"),
                    "--cov=app",
                    "--cov-report=xml:test_reports/integration_tests_coverage.xml",
                ]
            )

        result = pytest.main(test_args)
        success = result == 0

        self.results["integration_tests"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Integration tests PASSED")
        else:
            print("   ❌ Integration tests FAILED")

        print()
        return success

    def run_turkish_compliance_tests(self) -> bool:
        """Run Turkish compliance-specific tests."""
        print("🇹🇷 PHASE 6: Turkish Compliance Tests")
        print("   Testing KVKV/GDPR compliance and KDV financial regulations...")

        test_args = [
            str(self.test_dir / "integration" / "test_migration_integrity.py"),
            "-v" if self.verbose else "-q",
            "--tb=short",
            "-m",
            "turkish_compliance",
        ]

        if self.generate_report:
            test_args.extend(["--junitxml", str(self.report_dir / "turkish_compliance_report.xml")])

        result = pytest.main(test_args)
        success = result == 0

        self.results["turkish_compliance"] = {
            "success": success,
            "timestamp": datetime.now().isoformat(),
        }

        if success:
            print("   ✅ Turkish compliance tests PASSED")
        else:
            print("   ❌ Turkish compliance tests FAILED")

        print()
        return success

    def run_safety_checks(self) -> bool:
        """Run pre-migration safety checks."""
        print("🛡️  PRE-MIGRATION SAFETY CHECKS")
        print("   Validating environment for migration safety...")

        try:
            from tests.utils.migration_test_helpers import MigrationSafetyChecker
            from app.core.database import engine

            checker = MigrationSafetyChecker()
            is_safe, warnings = checker.validate_migration_safety(
                engine, "migration_integrity_tests"
            )

            if warnings:
                print("   ⚠️ Safety warnings detected:")
                for warning in warnings:
                    print(f"      - {warning}")

            if is_safe:
                print("   ✅ Environment is safe for migration testing")
            else:
                print("   ❌ Environment has safety concerns")

            self.results["safety_checks"] = {
                "success": is_safe,
                "warnings": warnings,
                "timestamp": datetime.now().isoformat(),
            }

            return is_safe

        except ImportError as e:
            print(f"   ⚠️ Could not import safety checker: {e}")
            return True  # Don't block tests if checker unavailable
        except Exception as e:
            print(f"   ❌ Safety check failed: {e}")
            return False

    def generate_summary_report(self):
        """Generate comprehensive test summary report."""
        if not self.generate_report:
            return

        print("📊 Generating Summary Report...")

        total_time = time.time() - self.start_time

        # Create comprehensive report
        report = {
            "test_run": {
                "timestamp": datetime.now().isoformat(),
                "duration_seconds": total_time,
                "test_suite": "Migration and Integrity Tests - Task 2.9",
                "platform": "FreeCAD CNC/CAM/CAD Production Platform",
            },
            "results": self.results,
            "summary": {
                "total_phases": len(self.results),
                "passed_phases": sum(1 for r in self.results.values() if r.get("success", False)),
                "failed_phases": sum(
                    1 for r in self.results.values() if not r.get("success", True)
                ),
                "overall_success": all(r.get("success", False) for r in self.results.values()),
            },
        }

        # Save JSON report
        report_file = (
            self.report_dir
            / f"migration_integrity_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(report_file, "w") as f:
            json.dump(report, f, indent=2)

        print(f"   ✅ Summary report saved: {report_file}")

        # Print summary
        print("\n" + "=" * 80)
        print("📊 TEST EXECUTION SUMMARY")
        print("=" * 80)
        print(f"⏱️  Total Time: {total_time:.2f} seconds")
        print(
            f"✅ Passed Phases: {report['summary']['passed_phases']}/{report['summary']['total_phases']}"
        )
        print(
            f"❌ Failed Phases: {report['summary']['failed_phases']}/{report['summary']['total_phases']}"
        )
        print()

        for phase, result in self.results.items():
            status = "✅ PASSED" if result.get("success", False) else "❌ FAILED"
            print(f"   {phase.replace('_', ' ').title()}: {status}")

        overall_status = "✅ SUCCESS" if report["summary"]["overall_success"] else "❌ FAILURE"
        print(f"\n🏁 OVERALL RESULT: {overall_status}")
        print("=" * 80)


def main():
    """Main entry point for test runner."""
    parser = argparse.ArgumentParser(
        description="Migration and Integrity Test Runner - Task 2.9",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_migration_integrity_tests.py --suite all --verbose --report
  python scripts/run_migration_integrity_tests.py --suite migration --safety-check
  python scripts/run_migration_integrity_tests.py --compliance --performance
        """,
    )

    parser.add_argument(
        "--suite",
        choices=["all", "migration", "constraints", "audit", "performance", "integration"],
        default="all",
        help="Test suite to run (default: all)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--report", "-r", action="store_true", help="Generate detailed test reports"
    )
    parser.add_argument(
        "--compliance", "-c", action="store_true", help="Run Turkish compliance-specific tests"
    )
    parser.add_argument(
        "--performance", "-p", action="store_true", help="Run performance benchmarks"
    )
    parser.add_argument(
        "--safety-check", "-s", action="store_true", help="Run pre-migration safety checks"
    )

    args = parser.parse_args()

    # Initialize test runner
    runner = MigrationTestRunner(verbose=args.verbose, generate_report=args.report)
    runner.print_banner()

    success = True

    # Run safety checks if requested
    if args.safety_check:
        success &= runner.run_safety_checks()
        print()

    # Run selected test suites
    if args.suite == "all" or args.suite == "migration":
        success &= runner.run_migration_safety_tests()

    if args.suite == "all" or args.suite == "constraints":
        success &= runner.run_constraint_validation_tests()

    if args.suite == "all" or args.suite == "audit":
        success &= runner.run_audit_integrity_tests()

    if args.suite == "all" or args.suite == "performance" or args.performance:
        success &= runner.run_performance_tests()

    if args.suite == "all" or args.suite == "integration":
        success &= runner.run_integration_tests()

    # Run Turkish compliance tests if requested
    if args.compliance:
        success &= runner.run_turkish_compliance_tests()

    # Generate summary report
    runner.generate_summary_report()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
