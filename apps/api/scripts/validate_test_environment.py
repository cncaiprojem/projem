#!/usr/bin/env python3
"""
Test Environment Validation Script - Task 2.9

Validates the migration and integrity test environment to ensure
all dependencies, configurations, and infrastructure are properly
set up for banking-level precision testing.

Usage:
    python scripts/validate_test_environment.py [--fix]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple


class TestEnvironmentValidator:
    """Validates test environment configuration and dependencies."""

    def __init__(self, fix_issues: bool = False):
        """Initialize validator."""
        self.fix_issues = fix_issues
        self.issues: List[str] = []
        self.warnings: List[str] = []
        self.fixes_applied: List[str] = []

        # Determine paths
        self.script_dir = Path(__file__).parent
        self.api_dir = self.script_dir.parent
        self.project_dir = self.api_dir.parent.parent
        self.test_dir = self.api_dir / "tests"

    def print_banner(self):
        """Print validation banner."""
        print("=" * 80)
        print("🔍 MIGRATION TEST ENVIRONMENT VALIDATION - TASK 2.9")
        print("   Banking-Level Precision Test Infrastructure Check")
        print("=" * 80)
        print()

    def validate_directory_structure(self) -> bool:
        """Validate required directory structure exists."""
        print("📁 Validating Directory Structure...")

        required_dirs = [
            self.test_dir,
            self.test_dir / "integration",
            self.test_dir / "utils",
            self.api_dir / "alembic",
            self.api_dir / "alembic" / "versions",
            self.api_dir / "scripts",
            self.project_dir / "docs" / "testing",
        ]

        missing_dirs = []
        for dir_path in required_dirs:
            if not dir_path.exists():
                missing_dirs.append(str(dir_path))
                if self.fix_issues:
                    try:
                        dir_path.mkdir(parents=True, exist_ok=True)
                        self.fixes_applied.append(f"Created directory: {dir_path}")
                    except Exception as e:
                        self.issues.append(f"Could not create directory {dir_path}: {e}")

        if missing_dirs and not self.fix_issues:
            self.issues.extend([f"Missing directory: {d}" for d in missing_dirs])

        if not missing_dirs or self.fix_issues:
            print("   ✅ Directory structure validated")
            return True
        else:
            print(f"   ❌ Missing directories: {len(missing_dirs)}")
            return False

    def validate_test_files(self) -> bool:
        """Validate required test files exist."""
        print("📄 Validating Test Files...")

        required_files = [
            self.test_dir / "integration" / "test_migration_integrity.py",
            self.test_dir / "utils" / "migration_test_helpers.py",
            self.test_dir / "test_migration_config.py",
            self.api_dir / "scripts" / "run_migration_integrity_tests.py",
            self.api_dir / "scripts" / "validate_test_environment.py",
            self.project_dir / "docs" / "testing" / "MIGRATION_INTEGRITY_TEST_SUITE.md",
        ]

        missing_files = []
        for file_path in required_files:
            if not file_path.exists():
                missing_files.append(str(file_path))

        if missing_files:
            self.issues.extend([f"Missing test file: {f}" for f in missing_files])
            print(f"   ❌ Missing test files: {len(missing_files)}")
            return False
        else:
            print("   ✅ All test files present")
            return True

    def validate_python_imports(self) -> bool:
        """Validate Python imports and dependencies."""
        print("🐍 Validating Python Dependencies...")

        required_imports = [
            ("pytest", "pytest testing framework"),
            ("sqlalchemy", "SQLAlchemy ORM"),
            ("alembic", "Alembic migration tool"),
            ("psycopg2", "PostgreSQL adapter"),
        ]

        optional_imports = [
            ("coverage", "Code coverage measurement"),
            ("pytest-cov", "Pytest coverage plugin"),
        ]

        import_failures = []

        # Check required imports
        for module, description in required_imports:
            try:
                __import__(module)
            except ImportError:
                import_failures.append(f"Required: {module} ({description})")

        # Check optional imports (warnings only)
        for module, description in optional_imports:
            try:
                __import__(module)
            except ImportError:
                self.warnings.append(
                    f"Optional: {module} ({description}) - some features may be limited"
                )

        if import_failures:
            self.issues.extend(import_failures)
            print(f"   ❌ Import failures: {len(import_failures)}")
            return False
        else:
            print("   ✅ Python dependencies available")
            return True

    def validate_database_connection(self) -> bool:
        """Validate database connection and configuration."""
        print("🗄️  Validating Database Connection...")

        try:
            # Check environment variables
            db_url = os.getenv("DATABASE_URL")
            if not db_url:
                self.issues.append("DATABASE_URL environment variable not set")
                return False

            # Try to import and test database connection
            from sqlalchemy import create_engine, text

            engine = create_engine(db_url)
            with engine.connect() as conn:
                result = conn.execute(text("SELECT version()"))
                version = result.scalar()

                if "PostgreSQL" not in version:
                    self.warnings.append(f"Expected PostgreSQL, got: {version}")

                print(f"   ✅ Database connection successful: {version}")
                return True

        except ImportError as e:
            self.issues.append(f"Database imports failed: {e}")
        except Exception as e:
            self.issues.append(f"Database connection failed: {e}")

        print("   ❌ Database connection failed")
        return False

    def validate_alembic_configuration(self) -> bool:
        """Validate Alembic migration configuration."""
        print("🔄 Validating Alembic Configuration...")

        try:
            from alembic.config import Config as AlembicConfig
            from alembic.script import ScriptDirectory

            alembic_dir = self.api_dir / "alembic"

            # Check alembic directory structure
            required_alembic_files = [
                alembic_dir / "env.py",
                alembic_dir / "versions",
            ]

            missing_files = [f for f in required_alembic_files if not f.exists()]
            if missing_files:
                self.issues.extend([f"Missing Alembic file: {f}" for f in missing_files])
                return False

            # Try to load Alembic configuration
            config = AlembicConfig()
            config.set_main_option("script_location", str(alembic_dir))

            script_dir = ScriptDirectory.from_config(config)
            revisions = list(script_dir.walk_revisions())

            print(f"   ✅ Alembic configuration valid ({len(revisions)} migrations)")
            return True

        except ImportError as e:
            self.issues.append(f"Alembic imports failed: {e}")
        except Exception as e:
            self.issues.append(f"Alembic configuration error: {e}")

        print("   ❌ Alembic configuration invalid")
        return False

    def validate_test_configuration(self) -> bool:
        """Validate pytest and test configuration."""
        print("🧪 Validating Test Configuration...")

        try:
            # Check pytest configuration
            pytest_ini = self.api_dir / "pytest.ini"
            if not pytest_ini.exists():
                self.warnings.append("pytest.ini not found - using default configuration")

            # Try to import test modules
            sys.path.insert(0, str(self.api_dir))

            try:
                from tests.utils.migration_test_helpers import MigrationTestEnvironment
                from tests.test_migration_config import MigrationTestConfig

                print("   ✅ Test helper imports successful")
            except ImportError as e:
                self.issues.append(f"Test helper import failed: {e}")
                return False

            # Check test markers and configuration
            from tests.test_migration_config import migration_markers

            print(f"   ✅ Test markers configured: {len(migration_markers)} markers")

            return True

        except Exception as e:
            self.issues.append(f"Test configuration validation failed: {e}")
            print("   ❌ Test configuration invalid")
            return False

    def validate_makefile_targets(self) -> bool:
        """Validate Makefile targets for test execution."""
        print("🔨 Validating Makefile Targets...")

        makefile_path = self.project_dir / "Makefile"
        if not makefile_path.exists():
            self.issues.append("Makefile not found")
            return False

        try:
            with open(makefile_path, "r", encoding="utf-8") as f:
                makefile_content = f.read()

            required_targets = [
                "test-migration-integrity",
                "test-migration-safety",
                "test-constraints",
                "test-audit-integrity",
                "test-performance",
                "test-turkish-compliance",
            ]

            missing_targets = []
            for target in required_targets:
                if target not in makefile_content:
                    missing_targets.append(target)

            if missing_targets:
                self.issues.extend([f"Missing Makefile target: {t}" for t in missing_targets])
                print(f"   ❌ Missing Makefile targets: {len(missing_targets)}")
                return False
            else:
                print("   ✅ All Makefile targets present")
                return True

        except Exception as e:
            self.issues.append(f"Makefile validation failed: {e}")
            print("   ❌ Makefile validation failed")
            return False

    def validate_security_requirements(self) -> bool:
        """Validate security and compliance requirements."""
        print("🔒 Validating Security Requirements...")

        try:
            # Check for required security modules
            import hashlib
            import json

            # Test hash calculation (for audit chains)
            test_data = {"test": "data"}
            test_json = json.dumps(test_data, sort_keys=True, separators=(",", ":"))
            test_hash = hashlib.sha256(test_json.encode("utf-8")).hexdigest()

            if len(test_hash) != 64:
                self.issues.append("SHA256 hash calculation failed")
                return False

            print("   ✅ Cryptographic functions available")

            # Check for Turkish compliance constants
            sys.path.insert(0, str(self.api_dir))
            from tests.test_migration_config import MigrationTestConfig

            if not hasattr(MigrationTestConfig, "DEFAULT_CURRENCY"):
                self.warnings.append("Turkish currency configuration not found")
            elif MigrationTestConfig.DEFAULT_CURRENCY != "TRY":
                self.warnings.append(
                    f"Expected TRY currency, got: {MigrationTestConfig.DEFAULT_CURRENCY}"
                )

            print("   ✅ Security requirements validated")
            return True

        except Exception as e:
            self.issues.append(f"Security validation failed: {e}")
            print("   ❌ Security validation failed")
            return False

    def run_smoke_test(self) -> bool:
        """Run a basic smoke test of the test infrastructure."""
        print("💨 Running Test Infrastructure Smoke Test...")

        try:
            # Try to create a test environment instance
            sys.path.insert(0, str(self.api_dir))
            from tests.utils.migration_test_helpers import MigrationTestEnvironment

            db_url = os.getenv(
                "DATABASE_URL", "postgresql+psycopg2://freecad:password@localhost:5432/freecad"
            )

            # This should not fail even if database is not available
            test_env = MigrationTestEnvironment(db_url)

            if hasattr(test_env, "_construct_test_db_url"):
                test_url = test_env._construct_test_db_url()
                if "migration_test_" not in test_url:
                    self.warnings.append("Test database URL format unexpected")

            print("   ✅ Test infrastructure smoke test passed")
            return True

        except Exception as e:
            self.issues.append(f"Smoke test failed: {e}")
            print("   ❌ Test infrastructure smoke test failed")
            return False

    def generate_summary(self) -> Dict[str, any]:
        """Generate validation summary."""
        validation_results = {
            "directory_structure": self.validate_directory_structure(),
            "test_files": self.validate_test_files(),
            "python_dependencies": self.validate_python_imports(),
            "database_connection": self.validate_database_connection(),
            "alembic_configuration": self.validate_alembic_configuration(),
            "test_configuration": self.validate_test_configuration(),
            "makefile_targets": self.validate_makefile_targets(),
            "security_requirements": self.validate_security_requirements(),
            "smoke_test": self.run_smoke_test(),
        }

        return {
            "validation_results": validation_results,
            "issues": self.issues,
            "warnings": self.warnings,
            "fixes_applied": self.fixes_applied,
            "overall_success": all(validation_results.values()) and len(self.issues) == 0,
        }

    def print_summary(self, summary: Dict[str, any]):
        """Print validation summary."""
        print("\n" + "=" * 80)
        print("📊 VALIDATION SUMMARY")
        print("=" * 80)

        print("🔍 Validation Results:")
        for test_name, result in summary["validation_results"].items():
            status = "✅ PASSED" if result else "❌ FAILED"
            print(f"   {test_name.replace('_', ' ').title()}: {status}")

        if summary["issues"]:
            print(f"\n❌ Issues Found ({len(summary['issues'])}):")
            for issue in summary["issues"]:
                print(f"   - {issue}")

        if summary["warnings"]:
            print(f"\n⚠️ Warnings ({len(summary['warnings'])}):")
            for warning in summary["warnings"]:
                print(f"   - {warning}")

        if summary["fixes_applied"]:
            print(f"\n🔧 Fixes Applied ({len(summary['fixes_applied'])}):")
            for fix in summary["fixes_applied"]:
                print(f"   - {fix}")

        overall_status = "✅ READY" if summary["overall_success"] else "❌ NOT READY"
        print(f"\n🏁 TEST ENVIRONMENT STATUS: {overall_status}")

        if summary["overall_success"]:
            print("\n🎉 Test environment is ready for migration and integrity testing!")
            print("   Run: make test-migration-integrity")
        else:
            print("\n🚨 Test environment requires fixes before testing can proceed.")
            print("   Review issues above and fix before running tests.")

        print("=" * 80)


def main():
    """Main entry point for validation script."""
    parser = argparse.ArgumentParser(
        description="Validate migration and integrity test environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--fix", action="store_true", help="Attempt to fix issues automatically")

    args = parser.parse_args()

    # Run validation
    validator = TestEnvironmentValidator(fix_issues=args.fix)
    validator.print_banner()

    summary = validator.generate_summary()
    validator.print_summary(summary)

    # Exit with appropriate code
    sys.exit(0 if summary["overall_success"] else 1)


if __name__ == "__main__":
    main()
