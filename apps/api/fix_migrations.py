#!/usr/bin/env python3
"""Fix migration chain issues and validate database setup for Tasks 1-4"""

import os
import re
import sys
import logging
from pathlib import Path
from typing import List, Tuple, Optional

# Configure logging for better debugging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Ensure UTF-8 encoding using shared utility
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))
from utils.encoding import setup_utf8_encoding
setup_utf8_encoding()

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
    
    logger.info("=" * 100)
    logger.info("MIGRATION CHAIN VALIDATION AND FIX REPORT")
    logger.info("=" * 100)
    
    # Check existing files
    existing_files = sorted([f.name for f in versions_dir.glob('*.py') if f.name != '__init__.py'])
    
    logger.info(f"\nFound {len(existing_files)} migration files")
    logger.info(f"Expected {len(expected_chain)} migration files")
    
    # Verify each expected migration
    logger.info("\n" + "=" * 100)
    logger.info("CHECKING MIGRATION CHAIN INTEGRITY")
    logger.info("=" * 100)
    
    issues_found = []
    fixes_needed = []
    
    for expected_file, expected_rev, expected_down in expected_chain:
        file_path = versions_dir / expected_file
        
        if not file_path.exists():
            issues_found.append(f"❌ MISSING: {expected_file}")
            continue
            
        # Read and check the file
        with open(file_path, 'r') as f:
            content = f.read()
            
        # Extract actual revision and down_revision
        rev_match = re.search(r'^revision[:\s]*(?:str\s*=\s*)?[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        down_match = re.search(r'^down_revision[:\s]*(?:Union\[str,\s*None\]\s*=\s*)?([^\n]+)', content, re.MULTILINE)
        
        if not rev_match:
            issues_found.append(f"❌ NO REVISION: {expected_file}")
            fixes_needed.append((expected_file, 'add_revision', expected_rev, expected_down))
            continue
            
        actual_rev = rev_match.group(1)
        down_raw = down_match.group(1) if down_match else 'None'
        actual_down = down_raw.strip().strip('"').strip("'")
        if actual_down == 'None':
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
            logger.info(f"✅ OK: {expected_file[:50]:50} Rev: {expected_rev[:25]:25}")
    
    # Check for extra files
    expected_files = {f for f, _, _ in expected_chain}
    extra_files = set(existing_files) - expected_files
    
    if extra_files:
        logger.info("\n" + "=" * 100)
        logger.info("EXTRA FILES FOUND (will be removed)")
        logger.info("=" * 100)
        for f in extra_files:
            issues_found.append(f"⚠️  EXTRA FILE: {f}")
            fixes_needed.append((f, 'remove', None, None))
    
    # Report issues
    if issues_found:
        logger.info("\n" + "=" * 100)
        logger.info("ISSUES FOUND")
        logger.info("=" * 100)
        for issue in issues_found:
            logger.info(issue)
    
    # Apply fixes
    if fixes_needed:
        logger.info("\n" + "=" * 100)
        logger.info("APPLYING FIXES")
        logger.info("=" * 100)
        
        for filename, action, expected_rev, expected_down in fixes_needed:
            file_path = versions_dir / filename
            
            if action == 'remove':
                logger.info(f"Removing extra file: {filename}")
                if file_path.exists():
                    file_path.unlink()
                    
            elif action in ['fix_revision', 'fix_down_revision', 'add_revision']:
                logger.info(f"Fixing {filename}: {action}")
                
                if action == 'add_revision':
                    # For files missing revision info, we need to add it
                    # This is complex and requires understanding the file structure
                    logger.info(f"  ⚠️  Manual fix needed for {filename} - missing revision info")
                else:
                    # Read file
                    with open(file_path, 'r') as f:
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
                    with open(file_path, 'w') as f:
                        f.write(content)
                    
                    logger.info(f"  ✅ Fixed: {filename}")
    
    # Final validation
    logger.info("\n" + "=" * 100)
    logger.info("FINAL VALIDATION")
    logger.info("=" * 100)
    
    all_valid = True
    for expected_file, expected_rev, expected_down in expected_chain:
        file_path = versions_dir / expected_file
        
        if not file_path.exists():
            logger.info(f"❌ Still missing: {expected_file}")
            all_valid = False
            continue
            
        with open(file_path, 'r') as f:
            content = f.read()
            
        rev_match = re.search(r'^revision[:\s]*(?:str\s*=\s*)?[\'"]([^\'"]+)[\'"]', content, re.MULTILINE)
        down_match = re.search(r'^down_revision[:\s]*(?:Union\[str,\s*None\]\s*=\s*)?([^\n]+)', content, re.MULTILINE)
        
        if rev_match:
            actual_rev = rev_match.group(1)
            down_raw = down_match.group(1) if down_match else 'None'
            actual_down = down_raw.strip().strip('"').strip("'")
            if actual_down == 'None':
                actual_down = None
                
            if actual_rev == expected_rev and actual_down == expected_down:
                logger.info(f"✅ Valid: {expected_file[:50]:50}")
            else:
                logger.info(f"❌ Invalid: {expected_file}")
                all_valid = False
    
    if all_valid:
        logger.info("\n" + "=" * 100)
        logger.info("✅ MIGRATION CHAIN IS NOW VALID AND READY FOR DEPLOYMENT")
        logger.info("=" * 100)
        logger.info("\nYou can now run: docker exec fc_api_dev alembic upgrade head")
    else:
        logger.info("\n" + "=" * 100)
        logger.info("❌ SOME ISSUES REMAIN - MANUAL INTERVENTION NEEDED")
        logger.info("=" * 100)
    
    return all_valid

if __name__ == '__main__':
    analyze_and_fix_migrations()