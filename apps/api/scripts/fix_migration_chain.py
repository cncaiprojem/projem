#!/usr/bin/env python3
"""Fix migration chain dependencies for proper ordering."""

import os
import re
from pathlib import Path

# Define the correct migration chain
MIGRATION_CHAIN = [
    ('20250817_0000-base_revision_enterprise_foundation.py', 'base_revision', None),
    ('20250817_1200-task_23_core_tables_optimization.py', '20250817_1200_task_23', 'base_revision'),
    ('20250817_1500-task_24_operational_tables_enterprise_erd_compliance.py', '20250817_1500_task_24', '20250817_1200_task_23'),
    ('20250817_1600-task_25_billing_tables_enterprise_financial_precision.py', '20250817_1600_task_25', '20250817_1500_task_24'),
    ('20250817_1700-task_26_security_audit_tables.py', '20250817_1700_task_26', '20250817_1600_task_25'),
    ('20250817_1800-task_27_global_constraints_performance_indexes.py', '20250817_1800_task_27', '20250817_1700_task_26'),
    ('20250817_1900-task_28_seed_data_migration.py', '20250817_1900_task_28', '20250817_1800_task_27'),
    ('20250817_2000-add_3d_printer_enum_gemini_fix.py', '20250817_2000_3d_printer', '20250817_1900_task_28'),
    ('20250817_1530_init_basic_tables.py', '20250817_1530_init_basic', '20250817_2000_3d_printer'),
    ('20250817_2030_task_31_enterprise_auth_fields.py', '20250817_2030_task_31', '20250817_1530_init_basic'),
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

def fix_migration_file(filepath, new_revision, new_down_revision):
    """Fix revision and down_revision in a migration file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Fix revision line
    content = re.sub(
        r"^revision\s*=\s*['\"].*?['\"]",
        f"revision = '{new_revision}'",
        content,
        flags=re.MULTILINE
    )
    
    # Fix down_revision line
    if new_down_revision is None:
        content = re.sub(
            r"^down_revision\s*=\s*.*$",
            "down_revision = None",
            content,
            flags=re.MULTILINE
        )
    else:
        content = re.sub(
            r"^down_revision\s*=\s*.*$",
            f"down_revision = '{new_down_revision}'",
            content,
            flags=re.MULTILINE
        )
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"Fixed {os.path.basename(filepath)}: revision={new_revision}, down_revision={new_down_revision}")

def main():
    """Fix all migration files in the chain."""
    base_dir = Path(__file__).parent.parent / 'alembic' / 'versions'
    
    print("Fixing migration chain dependencies...")
    print(f"Working directory: {base_dir}")
    
    for filename, revision, down_revision in MIGRATION_CHAIN:
        filepath = base_dir / filename
        if filepath.exists():
            fix_migration_file(filepath, revision, down_revision)
        else:
            print(f"WARNING: File not found: {filename}")
    
    print("\nMigration chain fixed successfully!")
    print("\nMigration order:")
    for i, (filename, revision, down_revision) in enumerate(MIGRATION_CHAIN, 1):
        arrow = "->" if down_revision else "START"
        print(f"{i:2}. {arrow} {revision} (from {down_revision or 'START'})")

if __name__ == "__main__":
    main()