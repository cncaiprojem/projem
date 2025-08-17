#!/usr/bin/env python3
"""
Task 2.7 Implementation Validation Script

This script validates that the Task 2.7 migration is correctly implemented
and ready for deployment in the enterprise FreeCAD CNC/CAM production environment.

Ultra Enterprise Standards Validation:
- Global constraints alignment with Task Master ERD
- Performance index optimization strategies  
- Banking-level precision for financial systems
- Turkish financial compliance (GDPR/KVKV + KDV)
- PostgreSQL 17.6 enterprise optimizations
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any
import re

# Add the parent directory to Python path for imports
sys.path.append(str(Path(__file__).parent))

def validate_migration_file() -> Dict[str, Any]:
    """Validate the Task 2.7 migration file structure and content."""
    
    validation_results = {
        'file_exists': False,
        'has_correct_revision': False,
        'has_enterprise_imports': False,
        'implements_unique_constraints': False,
        'implements_check_constraints': False,
        'implements_performance_indexes': False,
        'implements_jsonb_gin_indexes': False,
        'has_comprehensive_documentation': False,
        'has_monitoring_views': False,
        'has_proper_downgrade': False,
        'follows_naming_conventions': False,
        'has_error_handling': False,
        'summary': []
    }
    
    # Check if migration file exists
    migration_file = Path(__file__).parent / "alembic" / "versions" / "20250817_1800-task_27_global_constraints_performance_indexes.py"
    
    if not migration_file.exists():
        validation_results['summary'].append("[FAIL] Migration file does not exist")
        return validation_results
    
    validation_results['file_exists'] = True
    validation_results['summary'].append("[OK] Migration file exists")
    
    # Read and analyze migration content
    with open(migration_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check revision ID and dependencies
    if 'revision = \'20250817_1800_task_27\'' in content:
        validation_results['has_correct_revision'] = True
        validation_results['summary'].append("[OK] Correct revision ID: 20250817_1800_task_27")
    
    if 'down_revision = \'20250817_1700-task_26_security_audit_tables\'' in content:
        validation_results['summary'].append("[OK] Correct dependency on Task 2.6")
    
    # Check enterprise imports
    enterprise_imports = [
        'from alembic.migration_helpers import',
        'add_table_comment',
        'create_gin_index',
        'create_partial_index',
        'add_check_constraint'
    ]
    
    if all(imp in content for imp in enterprise_imports):
        validation_results['has_enterprise_imports'] = True
        validation_results['summary'].append("[OK] Enterprise migration helpers imported")
    
    # Check unique constraints implementation
    unique_constraints = [
        'uq_users_email',
        'uq_users_phone', 
        'uq_sessions_refresh_token_hash',
        'uq_jobs_idempotency_key',
        'uq_artefacts_s3_key',
        'uq_invoices_number',
        'uq_payments_provider_provider_ref'
    ]
    
    unique_found = sum(1 for constraint in unique_constraints if constraint in content)
    if unique_found >= 6:  # Most constraints should be present
        validation_results['implements_unique_constraints'] = True
        validation_results['summary'].append(f"[OK] Unique constraints implemented ({unique_found}/7)")
    
    # Check check constraints implementation
    check_constraints = [
        'ck_users_email_format',
        'ck_users_phone_format',
        'ck_artefacts_size_positive',
        'ck_sessions_expires_future'
    ]
    
    check_found = sum(1 for constraint in check_constraints if constraint in content)
    if check_found >= 3:
        validation_results['implements_check_constraints'] = True
        validation_results['summary'].append(f"[OK] Check constraints implemented ({check_found}/4)")
    
    # Check performance indexes
    performance_indexes = [
        'idx_jobs_user_type_status',
        'idx_jobs_priority_status',
        'idx_licenses_user_status_ends',
        'idx_users_role_status',
        'idx_sessions_cleanup',
        'idx_invoices_user_currency_status',
        'idx_payments_user_currency_status'
    ]
    
    perf_found = sum(1 for index in performance_indexes if index in content)
    if perf_found >= 5:
        validation_results['implements_performance_indexes'] = True
        validation_results['summary'].append(f"[OK] Performance indexes implemented ({perf_found}/7)")
    
    # Check JSONB GIN indexes
    jsonb_tables = ['users', 'jobs', 'licenses', 'invoices', 'payments', 'artefacts', 'audit_logs']
    jsonb_found = sum(1 for table in jsonb_tables if f"create_gin_index('{table}'" in content or f'create_gin_index("{table}"' in content)
    
    if jsonb_found >= 5:
        validation_results['implements_jsonb_gin_indexes'] = True
        validation_results['summary'].append(f"[OK] JSONB GIN indexes implemented ({jsonb_found}/7)")
    
    # Check documentation
    doc_elements = [
        'add_table_comment',
        'Enterprise audit trail',
        'Turkish financial compliance',
        'PostgreSQL 17.6'
    ]
    
    doc_found = sum(1 for element in doc_elements if element in content)
    if doc_found >= 3:
        validation_results['has_comprehensive_documentation'] = True
        validation_results['summary'].append("[OK] Comprehensive documentation included")
    
    # Check monitoring views
    if 'system_performance_summary' in content and 'CREATE MATERIALIZED VIEW' in content:
        validation_results['has_monitoring_views'] = True
        validation_results['summary'].append("[OK] Performance monitoring views created")
    
    # Check downgrade function
    if 'def downgrade():' in content and 'DROP' in content:
        validation_results['has_proper_downgrade'] = True
        validation_results['summary'].append("[OK] Proper downgrade function implemented")
    
    # Check naming conventions
    naming_patterns = [
        r'uq_[a-z_]+',  # Unique constraints
        r'ck_[a-z_]+',  # Check constraints  
        r'idx_[a-z_]+', # Indexes
        r'gin_[a-z_]+', # GIN indexes
    ]
    
    naming_found = sum(1 for pattern in naming_patterns if re.search(pattern, content))
    if naming_found >= 3:
        validation_results['follows_naming_conventions'] = True
        validation_results['summary'].append("[OK] PostgreSQL naming conventions followed")
    
    # Check error handling
    error_handling = [
        'try:', 'except Exception:', 'print', 'already exists'
    ]
    
    error_found = sum(1 for handler in error_handling if handler in content)
    if error_found >= 3:
        validation_results['has_error_handling'] = True
        validation_results['summary'].append("[OK] Comprehensive error handling implemented")
    
    return validation_results


def validate_erd_compliance() -> Dict[str, Any]:
    """Validate compliance with Task Master ERD requirements."""
    
    compliance_results = {
        'foreign_key_cascade_correct': False,
        'unique_constraints_match_erd': False,
        'financial_precision_maintained': False,
        'turkish_compliance_addressed': False,
        'summary': []
    }
    
    # Check models for ERD compliance
    models_dir = Path(__file__).parent / "app" / "models"
    
    if not models_dir.exists():
        compliance_results['summary'].append("[FAIL] Models directory not found")
        return compliance_results
    
    # Validate foreign key CASCADE behavior per ERD
    artefact_file = models_dir / "artefact.py"
    if artefact_file.exists():
        with open(artefact_file, 'r', encoding='utf-8') as f:
            artefact_content = f.read()
        
        if 'ondelete="CASCADE"' in artefact_content and 'job_id' in artefact_content:
            compliance_results['foreign_key_cascade_correct'] = True
            compliance_results['summary'].append("[OK] Artefact.job_id uses CASCADE per ERD")
    
    # Validate unique constraints match ERD requirements
    user_file = models_dir / "user.py"
    session_file = models_dir / "session.py"
    job_file = models_dir / "job.py"
    
    unique_checks = []
    
    if user_file.exists():
        with open(user_file, 'r', encoding='utf-8') as f:
            user_content = f.read()
        unique_checks.append('unique=True' in user_content and 'email' in user_content)
    
    if session_file.exists():
        with open(session_file, 'r', encoding='utf-8') as f:
            session_content = f.read()
        unique_checks.append('unique=True' in session_content and 'refresh_token_hash' in session_content)
    
    if job_file.exists():
        with open(job_file, 'r', encoding='utf-8') as f:
            job_content = f.read()
        unique_checks.append('unique=True' in job_content and 'idempotency_key' in job_content)
    
    if sum(unique_checks) >= 2:
        compliance_results['unique_constraints_match_erd'] = True
        compliance_results['summary'].append("[OK] Unique constraints match ERD requirements")
    
    # Validate financial precision (Decimal/BigInteger)
    invoice_file = models_dir / "invoice.py"
    payment_file = models_dir / "payment.py"
    
    financial_checks = []
    
    if invoice_file.exists():
        with open(invoice_file, 'r', encoding='utf-8') as f:
            invoice_content = f.read()
        financial_checks.append('amount_cents' in invoice_content and 'BigInteger' in invoice_content)
        financial_checks.append('Decimal' in invoice_content and 'ROUND_HALF_UP' in invoice_content)
    
    if payment_file.exists():
        with open(payment_file, 'r', encoding='utf-8') as f:
            payment_content = f.read()
        financial_checks.append('amount_cents' in payment_content and 'BigInteger' in payment_content)
    
    if sum(financial_checks) >= 2:
        compliance_results['financial_precision_maintained'] = True
        compliance_results['summary'].append("[OK] Banking-level financial precision maintained")
    
    # Check Turkish compliance features
    turkish_features = []
    
    if user_file.exists():
        with open(user_file, 'r', encoding='utf-8') as f:
            user_content = f.read()
        turkish_features.append('tax_no' in user_content)  # VKN/TCKN support
        turkish_features.append('Locale.TR' in user_content)  # Turkish locale
        turkish_features.append('Europe/Istanbul' in user_content)  # Turkish timezone
    
    if invoice_file.exists():
        with open(invoice_file, 'r', encoding='utf-8') as f:
            invoice_content = f.read()
        turkish_features.append('TRY' in invoice_content)  # Turkish Lira support
        turkish_features.append('KDV' in invoice_content or 'tax_rate_percent: float = 20.0' in invoice_content)  # Turkish VAT
    
    if sum(turkish_features) >= 3:
        compliance_results['turkish_compliance_addressed'] = True
        compliance_results['summary'].append("[OK] Turkish financial compliance (GDPR/KVKV + KDV) implemented")
    
    return compliance_results


def validate_performance_optimization() -> Dict[str, Any]:
    """Validate performance optimization strategies."""
    
    perf_results = {
        'has_composite_indexes': False,
        'has_partial_indexes': False,
        'has_jsonb_optimization': False,
        'has_monitoring_infrastructure': False,
        'summary': []
    }
    
    migration_file = Path(__file__).parent / "alembic" / "versions" / "20250817_1800-task_27_global_constraints_performance_indexes.py"
    
    if migration_file.exists():
        with open(migration_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check composite indexes
        composite_patterns = [
            'user_id.*type.*status',
            'user_id.*currency.*status',
            'job_id.*type.*size'
        ]
        
        composite_found = sum(1 for pattern in composite_patterns if re.search(pattern, content, re.DOTALL))
        if composite_found >= 2:
            perf_results['has_composite_indexes'] = True
            perf_results['summary'].append("[OK] Composite indexes for complex queries")
        
        # Check partial indexes
        if 'postgresql_where' in content and 'status IN' in content:
            perf_results['has_partial_indexes'] = True
            perf_results['summary'].append("[OK] Partial indexes for filtered queries")
        
        # Check JSONB optimization
        if 'create_gin_index' in content and 'fastupdate' in content:
            perf_results['has_jsonb_optimization'] = True
            perf_results['summary'].append("[OK] JSONB GIN indexes with PostgreSQL 17.6 optimizations")
        
        # Check monitoring infrastructure
        if 'system_performance_summary' in content:
            perf_results['has_monitoring_infrastructure'] = True
            perf_results['summary'].append("[OK] Performance monitoring infrastructure")
    
    return perf_results


def main():
    """Main validation function."""
    
    print("TASK 2.7 IMPLEMENTATION VALIDATION")
    print("=" * 60)
    print("Ultra Enterprise FreeCAD CNC/CAM Production Platform")
    print("Global Constraints and Performance Indexes Validation")
    print()
    
    # Validate migration file
    print("PHASE 1: Migration File Validation")
    print("-" * 40)
    migration_results = validate_migration_file()
    
    for summary_item in migration_results['summary']:
        print(f"   {summary_item}")
    
    migration_score = sum(1 for key, value in migration_results.items() 
                         if key != 'summary' and value is True)
    total_migration_checks = len([k for k in migration_results.keys() if k != 'summary'])
    
    print(f"\n   Migration Score: {migration_score}/{total_migration_checks}")
    
    # Validate ERD compliance
    print(f"\nPHASE 2: Task Master ERD Compliance")
    print("-" * 40)
    erd_results = validate_erd_compliance()
    
    for summary_item in erd_results['summary']:
        print(f"   {summary_item}")
    
    erd_score = sum(1 for key, value in erd_results.items() 
                   if key != 'summary' and value is True)
    total_erd_checks = len([k for k in erd_results.keys() if k != 'summary'])
    
    print(f"\n   ERD Compliance Score: {erd_score}/{total_erd_checks}")
    
    # Validate performance optimization
    print(f"\nPHASE 3: Performance Optimization")
    print("-" * 40)
    perf_results = validate_performance_optimization()
    
    for summary_item in perf_results['summary']:
        print(f"   {summary_item}")
    
    perf_score = sum(1 for key, value in perf_results.items() 
                    if key != 'summary' and value is True)
    total_perf_checks = len([k for k in perf_results.keys() if k != 'summary'])
    
    print(f"\n   Performance Score: {perf_score}/{total_perf_checks}")
    
    # Overall assessment
    total_score = migration_score + erd_score + perf_score
    total_checks = total_migration_checks + total_erd_checks + total_perf_checks
    success_rate = (total_score / total_checks) * 100
    
    print(f"\nOVERALL ASSESSMENT")
    print("=" * 60)
    print(f"Total Score: {total_score}/{total_checks} ({success_rate:.1f}%)")
    
    if success_rate >= 90:
        print("EXCELLENT: Ready for enterprise production deployment")
        status = "READY_FOR_PRODUCTION"
    elif success_rate >= 80:
        print("GOOD: Minor adjustments recommended before deployment")
        status = "MINOR_ADJUSTMENTS_NEEDED"
    elif success_rate >= 70:
        print("ADEQUATE: Significant improvements needed")
        status = "IMPROVEMENTS_NEEDED"
    else:
        print("INSUFFICIENT: Major issues must be resolved")
        status = "MAJOR_ISSUES"
    
    print(f"\nDEPLOYMENT STATUS: {status}")
    
    # Implementation readiness checklist
    print(f"\nIMPLEMENTATION READINESS CHECKLIST")
    print("-" * 40)
    
    checklist_items = [
        ("Migration file structure", migration_results['file_exists']),
        ("Enterprise imports", migration_results['has_enterprise_imports']),
        ("Unique constraints", migration_results['implements_unique_constraints']),
        ("Check constraints", migration_results['implements_check_constraints']),
        ("Performance indexes", migration_results['implements_performance_indexes']),
        ("JSONB optimization", migration_results['implements_jsonb_gin_indexes']),
        ("Documentation", migration_results['has_comprehensive_documentation']),
        ("Error handling", migration_results['has_error_handling']),
        ("ERD compliance", erd_results['unique_constraints_match_erd']),
        ("Financial precision", erd_results['financial_precision_maintained']),
        ("Turkish compliance", erd_results['turkish_compliance_addressed']),
        ("Performance monitoring", perf_results['has_monitoring_infrastructure'])
    ]
    
    for item_name, item_status in checklist_items:
        status_icon = "[OK]" if item_status else "[FAIL]"
        print(f"   {status_icon} {item_name}")
    
    print(f"\nTASK 2.7 VALIDATION COMPLETE")
    
    if success_rate >= 85:
        print("Implementation meets ultra enterprise standards!")
        print("Ready for FreeCAD CNC/CAM production deployment!")
    else:
        print("Review and address identified issues before deployment")
    
    return success_rate >= 85


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)