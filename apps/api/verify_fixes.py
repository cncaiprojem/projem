#!/usr/bin/env python
"""Verify that all PR #449 fixes are in place."""

from pathlib import Path


def verify_code_changes():
    """Verify that all code changes are in place."""
    
    print("Verifying code changes...")
    print("-" * 40)
    
    issues_found = []
    
    # Check metrics_extractor.py
    base_dir = Path(__file__).parent
    metrics_file = base_dir / "app" / "services" / "metrics_extractor.py"
    if metrics_file.exists():
        content = metrics_file.read_text(encoding='utf-8')
        
        # Check for CPU initialization fix
        if "_ = self._process.cpu_percent()  # First call always returns 0.0" in content:
            print("[OK] CPU initialization fix found")
        else:
            issues_found.append("CPU initialization fix not found")
        
        # Check for multiple materials handling
        if "materials_found = []" in content and "Multiple materials found in assembly" in content:
            print("[OK] Multiple materials handling found")
        else:
            issues_found.append("Multiple materials handling not found")
        
        # Check for memory-efficient STL reading
        if "sum(1 for line in ascii_f if 'facet normal' in line)" in content:
            print("[OK] Memory-efficient STL reading found")
        else:
            issues_found.append("Memory-efficient STL reading not found")
        
        # Check for resource module handling
        if "RESOURCE_AVAILABLE" in content:
            print("[OK] Resource module compatibility found")
        else:
            issues_found.append("Resource module compatibility not found")
    else:
        issues_found.append("metrics_extractor.py not found")
    
    # Check schemas/metrics.py
    metrics_schema = base_dir / "app" / "schemas" / "metrics.py"
    if metrics_schema.exists():
        content = metrics_schema.read_text(encoding='utf-8')
        
        # Check for METERS_TO_MILLIMETERS constant
        if "METERS_TO_MILLIMETERS = 1000" in content:
            print("[OK] METERS_TO_MILLIMETERS constant found")
        else:
            issues_found.append("METERS_TO_MILLIMETERS constant not found")
        
        # Check for declarative initialization
        if "kwargs = {}" in content and "return cls(**kwargs)" in content:
            print("[OK] Declarative initialization found")
        else:
            issues_found.append("Declarative initialization not found")
        
        # Check for locale improvements
        if "system_locale" in content:
            print("[OK] Locale improvements found")
        else:
            issues_found.append("Locale improvements not found")
    else:
        issues_found.append("schemas/metrics.py not found")
    
    # Check deterministic_exporter.py
    exporter_file = base_dir / "app" / "services" / "freecad" / "deterministic_exporter.py"
    if exporter_file.exists():
        content = exporter_file.read_text(encoding='utf-8')
        
        # Check for proper summary usage
        if "ModelMetricsSummary" in content and "from_full_metrics" in content:
            print("[OK] Summary method usage found")
        else:
            issues_found.append("Summary method usage not found")
    else:
        issues_found.append("deterministic_exporter.py not found")
    
    # Check test file
    test_file = base_dir / "tests" / "test_metrics_extraction.py"
    if test_file.exists():
        content = test_file.read_text(encoding='utf-8')
        
        # Check for improved test
        if "@patch.object(MetricsExtractor" in content:
            print("[OK] Improved test mocking found")
        else:
            issues_found.append("Improved test mocking not found")
    else:
        issues_found.append("test_metrics_extraction.py not found")
    
    print("\n" + "=" * 40)
    if issues_found:
        print("ISSUES FOUND:")
        for issue in issues_found:
            print(f"  - {issue}")
    else:
        print("ALL CODE CHANGES VERIFIED SUCCESSFULLY!")
    print("=" * 40)
    
    return len(issues_found) == 0


def main():
    """Run verification."""
    print("=" * 50)
    print("PR #449 FEEDBACK FIXES - CODE VERIFICATION")
    print("=" * 50)
    print()
    
    success = verify_code_changes()
    
    print("\n" + "=" * 50)
    if success:
        print("VERIFICATION COMPLETE - ALL FIXES APPLIED")
    else:
        print("VERIFICATION FAILED - SOME FIXES MISSING")
    print("=" * 50)
    
    return success


if __name__ == "__main__":
    import sys
    sys.exit(0 if main() else 1)