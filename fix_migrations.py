#!/usr/bin/env python3
"""Fix migration chain issues and validate database setup for Tasks 1-4"""

import os
import re
import sys
from pathlib import Path

# Set UTF-8 encoding for Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def analyze_and_fix_migrations():
    versions_dir = Path('apps/api/alembic/versions')
    
    # Expected migration chain based on task order
    expected_chain = [
        ('20250817_0000-base_revision_enterprise_foundation.py', 'base_revision', None),
        ('20250817_1200-task_23_core_tables_optimization.py', '20250817_1200_task_23', 'base_revision'),
        ('20250817_1500-task_24_operational_tables_enterprise_erd_compliance.py', '20250817_1500_task_24', '20250817_1200_task_23'),
        ('20250817_1600-task_25_billing_tables_enterprise_financial_precision.py', '20250817_1600_task_25', '20250817_1500_task_24'),
        ('20250817_1700-task_26_security_audit_tables.py', '20250817_1700_task_26', '20250817_1600_task_25'),
        ('20250817_1800-task_27_global_constraints_performance_indexes.py', '20250817_1800_task_27', '20250817_1700_task_26'),
        ('20250817_1900-task_28_seed_data_migration.py', '20250817_1900_task_28', '20250817_1800_task_27'),
        ('20250817_2000-add_3d_printer_enum_gemini_fix.py', '20250817_2000_3d_printer', '20250817_1900_task_28'),
        ('20250817_2030_task_31_enterprise_auth_fields.py', '20250817_2030_task_31', '20250817_2000_3d_printer'),
        ('20250817_2045_task_32_enterprise_sessions_table.py', '20250817_2045_task_32', '20250817_2030_task_31'),
        ('20250817_2100_task_35_oidc_accounts_table.py', '20250817_2100_task_35', '20250817_2045_task_32'),
        ('20250817_2200_task_36_magic_links_table.py', '20250817_2200_task_36', '20250817_2100_task_35'),
        ('20250817_2245_task_311_audit_correlation_pii_fields.py', '20250817_2245_task_311', '20250817_2200_task_36'),
        ('20250818_0000_task_37_mfa_totp_tables.py', '20250818_0000_task_37', '20250817_2245_task_311'),
        ('20250818_1000_task_41_license_domain_model.py', '20250818_1000_task_41', '20250818_0000_task_37'),
        ('20250818_1100_task_44_invoice_model_numbering_vat.py', '20250818_1100_task_44', '20250818_1000_task_41'),
        ('20250818_add_idempotency_records_table.py', '20250818_idempotency', '20250818_1100_task_44'),
        ('20250819_0000_task_47_notification_service_email_sms_provider_fallback.py', '20250819_0000_task_47', '20250818_idempotency'),
        ('20250819_1200_task_46_payment_provider_abstraction.py', '20250819_1200_task_46', '20250819_0000_task_47'),
        ('20250819_1230_task_48_license_notification_duplicate_prevention.py', '20250819_1230_task_48', '20250819_1200_task_46'),
        ('20250819_1245_task_49_job_cancellation_on_license_expiry.py', '20250819_1245_task_49', '20250819_1230_task_48'),
        ('20250819_task_411_concurrency_uniqueness_guards.py', '20250819_task_411', '20250819_1245_task_49'),
    ]
    
    print("=" * 100)
    print("MIGRATION CHAIN VALIDATION AND FIX REPORT")
    print("=" * 100)
    
    # Check existing files
    existing_files = sorted([f.name for f in versions_dir.glob('*.py') if f.name != '__init__.py'])
    
    print(f"\nFound {len(existing_files)} migration files")
    print(f"Expected {len(expected_chain)} migration files")
    
    # Verify each expected migration
    print("\n" + "=" * 100)
    print("CHECKING MIGRATION CHAIN INTEGRITY")
    print("=" * 100)
    
    issues_found = []
    fixes_needed = []
    
    for expected_file, expected_rev, expected_down in expected_chain:
        file_path = versions_dir / expected_file
        
        if not file_path.exists():
            issues_found.append(f"❌ MISSING: {expected_file}")
            continue
            
        # Read and check the file
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Extract actual revision and down_revision
        # Handle both quoted and unquoted formats
        rev_match = re.search(r"^revision[:\s]*(?:str\s*)?=\s*['\"]?([^'\"\n]+)['\"]?", content, re.MULTILINE)
        down_match = re.search(r"^down_revision[:\s]*(?:Union\[str,\s*None\]\s*)?=\s*([^\n]+)", content, re.MULTILINE)
        
        if not rev_match:
            issues_found.append(f"❌ NO REVISION: {expected_file}")
            fixes_needed.append((expected_file, 'add_revision', expected_rev, expected_down))
            continue
            
        actual_rev = rev_match.group(1).strip().strip('"').strip("'")
        down_raw = down_match.group(1) if down_match else 'None'
        actual_down = down_raw.strip().strip('"').strip("'")
        if actual_down == 'None' or actual_down == 'null':
            actual_down = None
            
        # Check if they match
        if actual_rev != expected_rev:
            issues_found.append(f"❌ WRONG REVISION: {expected_file}")
            issues_found.append(f"   Expected: {expected_rev}")
            issues_found.append(f"   Actual:   {actual_rev}")
            fixes_needed.append((expected_file, 'fix_revision', expected_rev, expected_down))
            
        if actual_down != expected_down:
            issues_found.append(f"❌ WRONG DOWN_REVISION: {expected_file}")
            issues_found.append(f"   Expected: {expected_down}")
            issues_found.append(f"   Actual:   {actual_down}")
            fixes_needed.append((expected_file, 'fix_down_revision', expected_rev, expected_down))
            
        if actual_rev == expected_rev and actual_down == expected_down:
            print(f"✅ OK: {expected_file[:50]:50} Rev: {expected_rev[:25]:25}")
    
    # Check for extra files
    expected_files = {f for f, _, _ in expected_chain}
    extra_files = set(existing_files) - expected_files
    
    if extra_files:
        print("\n" + "=" * 100)
        print("EXTRA FILES FOUND (will be removed)")
        print("=" * 100)
        for f in extra_files:
            issues_found.append(f"⚠️  EXTRA FILE: {f}")
            fixes_needed.append((f, 'remove', None, None))
    
    # Report issues
    if issues_found:
        print("\n" + "=" * 100)
        print("ISSUES FOUND")
        print("=" * 100)
        for issue in issues_found:
            print(issue)
    
    # Apply fixes
    if fixes_needed:
        print("\n" + "=" * 100)
        print("APPLYING FIXES")
        print("=" * 100)
        
        for filename, action, expected_rev, expected_down in fixes_needed:
            file_path = versions_dir / filename
            
            if action == 'remove':
                print(f"Removing extra file: {filename}")
                if file_path.exists():
                    file_path.unlink()
                    
            elif action in ['fix_revision', 'fix_down_revision', 'add_revision']:
                print(f"Fixing {filename}: {action}")
                
                if action == 'add_revision':
                    # For files missing revision info, we need to add it
                    # This is complex and requires understanding the file structure
                    print(f"  ⚠️  Manual fix needed for {filename} - missing revision info")
                else:
                    # Read file
                    with open(file_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Fix revision
                    if action == 'fix_revision':
                        content = re.sub(
                            r'^revision[:\s]*(?:str\s*=\s*)?[\'"][^\'"]+[\'"]',
                            f"revision: str = '{expected_rev}'",
                            content, 
                            flags=re.MULTILINE
                        )
                    
                    # Fix down_revision
                    if action == 'fix_down_revision':
                        if expected_down is None:
                            new_down = "down_revision: Union[str, None] = None"
                        else:
                            new_down = f"down_revision: Union[str, None] = '{expected_down}'"
                        
                        content = re.sub(
                            r'^down_revision[:\s]*(?:Union\[str,\s*None\]\s*=\s*)?[^\n]+',
                            new_down,
                            content,
                            flags=re.MULTILINE
                        )
                    
                    # Write back
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    
                    print(f"  ✅ Fixed: {filename}")
    
    # Final validation
    print("\n" + "=" * 100)
    print("FINAL VALIDATION")
    print("=" * 100)
    
    all_valid = True
    for expected_file, expected_rev, expected_down in expected_chain:
        file_path = versions_dir / expected_file
        
        if not file_path.exists():
            print(f"❌ Still missing: {expected_file}")
            all_valid = False
            continue
            
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Handle both quoted and unquoted formats
        rev_match = re.search(r"^revision[:\s]*(?:str\s*)?=\s*['\"]?([^'\"\n]+)['\"]?", content, re.MULTILINE)
        down_match = re.search(r"^down_revision[:\s]*(?:Union\[str,\s*None\]\s*)?=\s*([^\n]+)", content, re.MULTILINE)
        
        if rev_match:
            actual_rev = rev_match.group(1).strip().strip('"').strip("'")
            down_raw = down_match.group(1) if down_match else 'None'
            actual_down = down_raw.strip().strip('"').strip("'")
            if actual_down == 'None' or actual_down == 'null':
                actual_down = None
                
            if actual_rev == expected_rev and actual_down == expected_down:
                print(f"✅ Valid: {expected_file[:50]:50}")
            else:
                print(f"❌ Invalid: {expected_file}")
                all_valid = False
    
    if all_valid:
        print("\n" + "=" * 100)
        print("✅ MIGRATION CHAIN IS NOW VALID AND READY FOR DEPLOYMENT")
        print("=" * 100)
        print("\nYou can now run: docker exec fc_api_dev alembic upgrade head")
    else:
        print("\n" + "=" * 100)
        print("❌ SOME ISSUES REMAIN - MANUAL INTERVENTION NEEDED")
        print("=" * 100)
    
    return all_valid

if __name__ == '__main__':
    analyze_and_fix_migrations()