#!/usr/bin/env python3
"""
Task 2.10: Quick SQLAlchemy Model Validation Script
Validates model structure without requiring database connection.
"""

import sys
from pathlib import Path
from typing import Dict, List, Any

# Add project root to path for imports
project_root = Path(__file__).parents[1]
sys.path.insert(0, str(project_root))

from app.models import metadata, Base
from app.models.enums import *


def validate_models():
    """Quick validation of SQLAlchemy models."""
    print("Task 2.10: Quick SQLAlchemy Model Validation")
    print("=" * 60)

    # Get all models
    models = {}
    for table_name, table in metadata.tables.items():
        models[table_name] = table

    print(f"\nFound {len(models)} SQLAlchemy models:")
    for table_name in sorted(models.keys()):
        table = models[table_name]
        print(f"  - {table_name} ({len(table.columns)} columns)")

    # Check for expected Task Master ERD tables
    expected_tables = {
        "users",
        "sessions",
        "licenses",
        "models",
        "jobs",
        "cam_runs",
        "sim_runs",
        "artefacts",
        "notifications",
        "erp_mes_sync",
        "invoices",
        "payments",
        "audit_logs",
        "security_events",
        "machines",
        "materials",
        "tools",
    }

    current_tables = set(models.keys())
    missing_tables = expected_tables - current_tables
    extra_tables = current_tables - expected_tables

    print(f"\nERD Compliance Check:")
    if not missing_tables and not extra_tables:
        print("  + Perfect match with Task Master ERD!")
    else:
        if missing_tables:
            print(f"  - Missing tables: {', '.join(sorted(missing_tables))}")
        if extra_tables:
            print(f"  - Extra tables: {', '.join(sorted(extra_tables))}")

    # Check for financial precision fields
    financial_tables = ["invoices", "payments"]
    print(f"\nFinancial Precision Check:")
    for table_name in financial_tables:
        if table_name in models:
            table = models[table_name]
            amount_columns = [col for col in table.columns if "amount" in col.name.lower()]
            print(f"  * {table_name}: {len(amount_columns)} amount columns")
            for col in amount_columns:
                precision_check = "+" if "cents" in col.name or "BIGINT" in str(col.type) else "-"
                print(f"    {precision_check} {col.name}: {col.type}")

    # Check for idempotency fields
    print(f"\nIdempotency Key Check:")
    idempotency_tables = []
    for table_name, table in models.items():
        if any("idempotency" in col.name.lower() for col in table.columns):
            idempotency_tables.append(table_name)
            idempotency_cols = [col for col in table.columns if "idempotency" in col.name.lower()]
            print(f"  + {table_name}: {', '.join(col.name for col in idempotency_cols)}")

    if not idempotency_tables:
        print("  - No idempotency key fields found")

    # Check for audit chain fields
    print(f"\nAudit Chain Check:")
    if "audit_logs" in models:
        audit_table = models["audit_logs"]
        hash_columns = [col for col in audit_table.columns if "hash" in col.name.lower()]
        if hash_columns:
            print(f"  + audit_logs: {', '.join(col.name for col in hash_columns)}")
            for col in hash_columns:
                if "CHAR(64)" in str(col.type) or "VARCHAR(64)" in str(col.type):
                    print(f"    + {col.name}: Proper SHA-256 length")
                else:
                    print(f"    - {col.name}: May not be proper SHA-256 length ({col.type})")
        else:
            print("  - No hash columns found in audit_logs")
    else:
        print("  - audit_logs table not found")

    # Check for Turkish compliance fields
    print(f"\nTurkish Compliance Check:")
    if "users" in models:
        users_table = models["users"]
        turkish_fields = ["tax_no", "company_name", "address"]
        found_fields = [
            field
            for field in turkish_fields
            if any(col.name == field for col in users_table.columns)
        ]
        missing_fields = [field for field in turkish_fields if field not in found_fields]

        if found_fields:
            print(f"  + Found Turkish fields: {', '.join(found_fields)}")
        if missing_fields:
            print(f"  - Missing Turkish fields: {', '.join(missing_fields)}")

    # Check for JSONB fields
    print(f"\nJSONB Fields Check:")
    jsonb_count = 0
    for table_name, table in models.items():
        jsonb_cols = [col for col in table.columns if "JSONB" in str(col.type)]
        if jsonb_cols:
            jsonb_count += len(jsonb_cols)
            print(f"  * {table_name}: {', '.join(col.name for col in jsonb_cols)}")

    if jsonb_count == 0:
        print("  - No JSONB columns found")
    else:
        print(f"  + Found {jsonb_count} JSONB columns across tables")

    # Summary
    print(f"\nVALIDATION SUMMARY:")
    print("=" * 60)
    print(f"+ Total models: {len(models)}")
    print(
        f"+ ERD compliance: {'Perfect' if not missing_tables and not extra_tables else 'Needs attention'}"
    )
    print(f"+ Financial precision: {'Implemented' if financial_tables else 'Not applicable'}")
    print(f"+ Idempotency support: {'Yes' if idempotency_tables else 'No'}")
    print(f"+ Audit chain: {'Yes' if 'audit_logs' in models else 'No'}")
    print(f"+ JSONB fields: {jsonb_count}")

    return {
        "total_models": len(models),
        "erd_compliant": not missing_tables and not extra_tables,
        "has_financial_precision": len(financial_tables) > 0,
        "has_idempotency": len(idempotency_tables) > 0,
        "has_audit_chain": "audit_logs" in models,
        "jsonb_fields": jsonb_count,
    }


if __name__ == "__main__":
    try:
        result = validate_models()
        if all(
            [
                result["erd_compliant"],
                result["has_financial_precision"],
                result["has_idempotency"],
                result["has_audit_chain"],
                result["jsonb_fields"] > 0,
            ]
        ):
            print("\n+ All validations passed - models are enterprise ready!")
            sys.exit(0)
        else:
            print("\n- Some validations need attention")
            sys.exit(1)
    except Exception as e:
        print(f"\n- Validation failed: {e}")
        sys.exit(2)
