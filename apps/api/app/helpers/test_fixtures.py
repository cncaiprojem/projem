"""
Test fixtures for core entities with query examples demonstrating index usage.
Task 2.10: Ultra Enterprise test fixtures with banking-level validation examples.

This module provides comprehensive test fixtures that demonstrate:
- Idempotent job creation semantics
- Index usage optimization examples 
- Turkish compliance test scenarios
- Financial precision validation examples
- Audit chain test scenarios
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.helpers.canonical_json import AuditChainManager
from app.models.enums import (
    AuditAction,
    Currency,
    InvoiceStatus,
    JobStatus,
    JobType,
    PaymentStatus,
    UserRole,
)


class EnterpriseTestFixtures:
    """Ultra enterprise test fixtures with demonstration of index usage."""

    @staticmethod
    def create_test_users() -> list[dict[str, Any]]:
        """
        Create test users demonstrating Turkish compliance and index usage.
        
        INDEXES DEMONSTRATED:
        - idx_users_email (unique index on email)
        - idx_users_phone (partial index WHERE phone IS NOT NULL)
        - idx_users_tax_no (partial index WHERE tax_no IS NOT NULL)
        - idx_users_created_at (descending index for recent user queries)
        """

        return [
            {
                # Turkish company user with VKN
                "email": "ceo@turkishcnc.com.tr",
                "phone": "+905551234567",  # Turkish mobile format
                "role": UserRole.ADMIN,
                "company_name": "Turkish CNC Manufacturing Ltd.",
                "tax_no": "1234567890",  # Valid Turkish VKN
                "address": "Atatürk Caddesi No:123, Ankara, Türkiye",
                "locale": "tr",
                "timezone": "Europe/Istanbul",
                "is_active": True,
                "is_verified": True,
                "user_metadata": {
                    "kvkv_consent": True,
                    "gdpr_consent": True,
                    "marketing_consent": False,
                    "preferred_currency": "TRY",
                    "tax_office": "Ankara Vergi Dairesi",
                    "industry": "manufacturing"
                }
            },
            {
                # Individual Turkish user with TCKN
                "email": "engineer@example.com.tr",
                "phone": "05551234568",  # Turkish mobile without country code
                "role": UserRole.ENGINEER,
                "company_name": None,
                "tax_no": "12345678901",  # Valid Turkish TCKN (11 digits)
                "address": "İstiklal Caddesi No:456, İstanbul, Türkiye",
                "locale": "tr",
                "timezone": "Europe/Istanbul",
                "is_active": True,
                "is_verified": True,
                "user_metadata": {
                    "kvkv_consent": True,
                    "gdpr_consent": True,
                    "marketing_consent": True,
                    "preferred_currency": "TRY",
                    "professional_license": "CNC_ENGINEER_TR_2025"
                }
            },
            {
                # International user for multi-currency testing
                "email": "international@globalcnc.com",
                "phone": "+491234567890",  # German phone number
                "role": UserRole.ENGINEER,
                "company_name": "Global CNC Solutions GmbH",
                "tax_no": None,  # No Turkish tax number
                "address": "Hauptstraße 789, Berlin, Germany",
                "locale": "en",
                "timezone": "Europe/Berlin",
                "is_active": True,
                "is_verified": True,
                "user_metadata": {
                    "gdpr_consent": True,
                    "marketing_consent": True,
                    "preferred_currency": "EUR",
                    "certifications": ["ISO_9001", "CE_MARKING"]
                }
            }
        ]

    @staticmethod
    def create_test_jobs_with_idempotency() -> list[dict[str, Any]]:
        """
        Create test jobs demonstrating idempotency key usage and index optimization.
        
        INDEXES DEMONSTRATED:
        - idx_jobs_idempotency_key (partial index WHERE idempotency_key IS NOT NULL)
        - idx_jobs_type_status (composite index for job queue queries)
        - idx_jobs_user_id (foreign key index)
        - idx_jobs_created_at (descending index for recent jobs)
        """

        base_timestamp = datetime.now(UTC)

        return [
            {
                # CAD generation job with idempotency
                "idempotency_key": f"cad_gen_{uuid4().hex}",
                "user_id": 1,  # Reference to Turkish company user
                "type": JobType.CAD_GENERATE,
                "status": JobStatus.PENDING,
                "priority": 5,
                "input_params": {
                    "operation_type": "parametric_modeling",
                    "part_type": "bracket",
                    "material": "aluminum_6061",
                    "dimensions": {
                        "length_mm": 100.0,
                        "width_mm": 50.0,
                        "height_mm": 25.0
                    },
                    "tolerances": {
                        "general": "±0.1",
                        "critical": "±0.05"
                    },
                    "turkish_standards": ["TS_EN_ISO_2768"]
                },
                "timeout_seconds": 1800,  # 30 minutes
                "max_retries": 3,
                "created_at": base_timestamp
            },
            {
                # CAM processing job with Turkish machine settings
                "idempotency_key": f"cam_proc_{uuid4().hex}",
                "user_id": 1,
                "type": JobType.CAM_PROCESS,
                "status": JobStatus.RUNNING,
                "priority": 7,
                "task_id": f"celery_task_{uuid4().hex}",
                "input_params": {
                    "operation_type": "2.5d_milling",
                    "strategy": "adaptive_clearing",
                    "machine_id": 1,
                    "tool_library": "turkish_standard_tools",
                    "cutting_parameters": {
                        "spindle_speed_rpm": 12000,
                        "feed_rate_mm_min": 2500,
                        "depth_of_cut_mm": 2.0,
                        "coolant": "flood"
                    },
                    "safety_margins": {
                        "rapid_height_mm": 10.0,
                        "clearance_height_mm": 2.0
                    },
                    "quality_settings": {
                        "surface_finish": "N6",  # Turkish surface roughness standard
                        "dimensional_tolerance": "IT7"
                    }
                },
                "progress": 45,
                "started_at": base_timestamp - timedelta(minutes=15),
                "timeout_seconds": 3600,  # 1 hour
                "metrics": {
                    "estimated_runtime_minutes": 25,
                    "material_removal_rate": 15.2,
                    "tool_wear_prediction": "low"
                },
                "created_at": base_timestamp - timedelta(minutes=20)
            },
            {
                # Failed job demonstrating retry logic
                "idempotency_key": f"sim_run_{uuid4().hex}",
                "user_id": 2,  # Reference to engineer user
                "type": JobType.SIM_RUN,
                "status": JobStatus.FAILED,
                "priority": 3,
                "input_params": {
                    "simulation_type": "collision_detection",
                    "model_id": 1,
                    "machine_id": 1,
                    "accuracy_level": "high"
                },
                "error_code": "MEMORY_LIMIT_EXCEEDED",
                "error_message": "Simulation requires more than allocated memory limit",
                "retry_count": 2,
                "max_retries": 3,
                "started_at": base_timestamp - timedelta(hours=2),
                "finished_at": base_timestamp - timedelta(hours=1, minutes=45),
                "created_at": base_timestamp - timedelta(hours=2, minutes=10)
            }
        ]

    @staticmethod
    def create_test_invoices_financial_precision() -> list[dict[str, Any]]:
        """
        Create test invoices demonstrating financial precision and Turkish compliance.
        
        INDEXES DEMONSTRATED:
        - idx_invoices_user_id (foreign key index)
        - idx_invoices_number (unique index on invoice number)
        - idx_invoices_status (partial index for unpaid invoices)
        - idx_invoices_due_at (partial index for overdue invoice queries)
        """

        base_date = datetime.now(UTC).date()

        return [
            {
                # Turkish invoice with KDV (VAT)
                "user_id": 1,
                "number": f"TR-INV-{base_date.strftime('%Y%m%d')}-001",
                "amount_cents": 120000,  # 1,200.00 TRY (including 20% KDV)
                "currency": Currency.TRY,
                "status": InvoiceStatus.SENT,
                "issued_at": datetime.now(UTC),
                "due_at": datetime.now(UTC) + timedelta(days=30),
                "meta": {
                    "line_items": [
                        {
                            "description": "CNC Machining Services - Aluminum Bracket",
                            "quantity": 10,
                            "unit_price_cents": 10000,  # 100.00 TRY per piece
                            "subtotal_cents": 100000,   # 1,000.00 TRY
                            "tax_rate_percent": 20.0,   # Turkish KDV
                            "tax_cents": 20000,         # 200.00 TRY KDV
                            "total_cents": 120000       # 1,200.00 TRY total
                        }
                    ],
                    "tax_breakdown": {
                        "subtotal_cents": 100000,
                        "kdv_rate_percent": 20.0,
                        "kdv_amount_cents": 20000,
                        "total_cents": 120000,
                        "currency": "TRY"
                    },
                    "turkish_compliance": {
                        "tax_office": "Ankara Vergi Dairesi",
                        "tax_number": "1234567890",
                        "invoice_series": "TR",
                        "electronic_invoice": True
                    },
                    "payment_terms": {
                        "net_days": 30,
                        "early_payment_discount": {
                            "days": 10,
                            "discount_percent": 2.0
                        }
                    }
                }
            },
            {
                # Multi-currency invoice (EUR) for international client
                "user_id": 3,
                "number": f"EUR-INV-{base_date.strftime('%Y%m%d')}-001",
                "amount_cents": 150000,  # 1,500.00 EUR
                "currency": Currency.EUR,
                "status": InvoiceStatus.PAID,
                "issued_at": datetime.now(UTC) - timedelta(days=15),
                "due_at": datetime.now(UTC) - timedelta(days=15) + timedelta(days=30),
                "meta": {
                    "line_items": [
                        {
                            "description": "Custom CAD Design Service",
                            "quantity": 5,
                            "unit_price_cents": 25000,  # 250.00 EUR per design
                            "subtotal_cents": 125000,   # 1,250.00 EUR
                            "tax_rate_percent": 20.0,   # Standard EU VAT
                            "tax_cents": 25000,         # 250.00 EUR VAT
                            "total_cents": 150000       # 1,500.00 EUR total
                        }
                    ],
                    "currency_conversion": {
                        "base_currency": "EUR",
                        "exchange_rate_to_try": Decimal("32.50"),
                        "try_equivalent_cents": 487500  # Approximate TRY equivalent
                    },
                    "payment_terms": {
                        "net_days": 30,
                        "currency": "EUR",
                        "wire_transfer_details": {
                            "iban": "DE89370400440532013000",
                            "swift": "COBADEFFXXX",
                            "bank_name": "Deutsche Bank AG"
                        }
                    }
                }
            }
        ]

    @staticmethod
    def create_test_payments_precision() -> list[dict[str, Any]]:
        """
        Create test payments demonstrating financial precision validation.
        
        INDEXES DEMONSTRATED:
        - idx_payments_invoice_id (foreign key index for payment tracking)
        - idx_payments_user_id (foreign key index)
        - idx_payments_provider_ref (unique index for provider transaction IDs)
        - idx_payments_status (partial index for pending payments)
        """

        return [
            {
                # Turkish bank transfer payment
                "invoice_id": 1,
                "user_id": 1,
                "provider": "turkish_bank_transfer",
                "provider_ref": f"TR_BANK_TXN_{uuid4().hex[:16].upper()}",
                "method": "bank_transfer",
                "currency": Currency.TRY,
                "amount_cents": 120000,  # Exact invoice amount
                "fee_cents": 500,        # 5.00 TRY bank fee
                "status": PaymentStatus.COMPLETED,
                "processed_at": datetime.now(UTC) - timedelta(minutes=30),
                "meta": {
                    "bank_details": {
                        "iban": "TR330006100519786457841326",
                        "bank_name": "Türkiye İş Bankası",
                        "branch_code": "0519",
                        "reference_number": "TR2025011500123456"
                    },
                    "turkish_compliance": {
                        "central_bank_reporting": True,
                        "fatca_reporting": False,
                        "aml_check_passed": True
                    },
                    "precision_validation": {
                        "original_amount_decimal": "1200.00",
                        "processed_amount_cents": 120000,
                        "precision_loss_check": "passed"
                    }
                }
            },
            {
                # International payment with currency conversion
                "invoice_id": 2,
                "user_id": 3,
                "provider": "stripe_international",
                "provider_ref": f"pi_{uuid4().hex[:24]}",
                "method": "credit_card",
                "currency": Currency.EUR,
                "amount_cents": 150000,  # 1,500.00 EUR
                "fee_cents": 4500,       # 45.00 EUR Stripe fee (3%)
                "status": PaymentStatus.COMPLETED,
                "processed_at": datetime.now(UTC) - timedelta(days=5),
                "meta": {
                    "card_details": {
                        "brand": "visa",
                        "last4": "4242",
                        "exp_month": 12,
                        "exp_year": 2027,
                        "country": "DE"
                    },
                    "currency_conversion": {
                        "processing_currency": "EUR",
                        "settlement_currency": "TRY",
                        "exchange_rate": "32.50",
                        "settlement_amount_cents": 487500  # 4,875.00 TRY
                    },
                    "risk_assessment": {
                        "fraud_score": 12,  # Low risk (0-100 scale)
                        "3ds_authenticated": True,
                        "country_risk": "low"
                    }
                }
            }
        ]

    @staticmethod
    def create_test_audit_logs_chain() -> list[dict[str, Any]]:
        """
        Create test audit logs demonstrating hash chain integrity.
        
        INDEXES DEMONSTRATED:
        - idx_audit_logs_user_id (partial index WHERE user_id IS NOT NULL)
        - idx_audit_logs_action (index for action-based queries)
        - idx_audit_logs_entity (composite index on entity_type, entity_id)
        - idx_audit_logs_created_at (descending index for recent activity)
        - idx_audit_logs_chain_hash (unique index for hash integrity)
        """

        base_timestamp = datetime.now(UTC)

        # Create genesis record
        genesis_record = {
            "action": "system_init",
            "entity_type": "system",
            "timestamp": base_timestamp.isoformat().replace('+00:00', 'Z')
        }

        genesis_hash = AuditChainManager.compute_hash_chain(genesis_record, None)

        # Create chain of audit records
        audit_records = [
            {
                # Genesis record
                "user_id": None,
                "action": AuditAction.CREATE,
                "entity_type": "system",
                "entity_id": None,
                "payload": genesis_record,
                "ip_address": None,
                "user_agent": None,
                "session_id": None,
                "chain_hash": genesis_hash,
                "prev_chain_hash": None,
                "created_at": base_timestamp
            }
        ]

        # User creation audit
        user_create_record = {
            "action": "user_create",
            "entity_type": "user",
            "entity_id": "1",
            "timestamp": (base_timestamp + timedelta(minutes=1)).isoformat().replace('+00:00', 'Z'),
            "user_id": 1,
            "ip_address": "192.168.1.100",
            "entity_data": {
                "email": "ceo@turkishcnc.com.tr",
                "role": "admin",
                "company_name": "Turkish CNC Manufacturing Ltd.",
                "tax_no": "1234567890",
                "kvkv_consent": True
            },
            "metadata": {
                "registration_source": "web",
                "turkish_compliance": True,
                "gdpr_basis": "contract"
            }
        }

        user_create_hash = AuditChainManager.compute_hash_chain(
            user_create_record, genesis_hash
        )

        audit_records.append({
            "user_id": 1,
            "action": AuditAction.USER_CREATE,
            "entity_type": "user",
            "entity_id": 1,
            "payload": user_create_record,
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "session_id": 1,
            "chain_hash": user_create_hash,
            "prev_chain_hash": genesis_hash,
            "created_at": base_timestamp + timedelta(minutes=1)
        })

        # Invoice creation audit
        invoice_create_record = {
            "action": "invoice_create",
            "entity_type": "invoice",
            "entity_id": "1",
            "timestamp": (base_timestamp + timedelta(minutes=30)).isoformat().replace('+00:00', 'Z'),
            "user_id": 1,
            "ip_address": "192.168.1.100",
            "entity_data": {
                "number": f"TR-INV-{base_timestamp.strftime('%Y%m%d')}-001",
                "amount_cents": 120000,
                "currency": "TRY",
                "status": "sent"
            },
            "metadata": {
                "turkish_tax_compliance": True,
                "kdv_rate": 20.0,
                "electronic_invoice": True
            }
        }

        invoice_create_hash = AuditChainManager.compute_hash_chain(
            invoice_create_record, user_create_hash
        )

        audit_records.append({
            "user_id": 1,
            "action": AuditAction.CREATE,
            "entity_type": "invoice",
            "entity_id": 1,
            "payload": invoice_create_record,
            "ip_address": "192.168.1.100",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "session_id": 1,
            "chain_hash": invoice_create_hash,
            "prev_chain_hash": user_create_hash,
            "created_at": base_timestamp + timedelta(minutes=30)
        })

        return audit_records

    @staticmethod
    def create_query_examples() -> dict[str, str]:
        """
        Provide SQL query examples demonstrating index usage.
        
        These queries show how to effectively use the database indexes
        for common application patterns.
        """

        return {
            "recent_user_registrations": """
                -- Uses idx_users_created_at (DESC)
                SELECT email, company_name, created_at
                FROM users 
                WHERE created_at >= NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 20;
            """,

            "active_turkish_users_with_tax_numbers": """
                -- Uses idx_users_tax_no (partial index WHERE tax_no IS NOT NULL)
                SELECT email, company_name, tax_no
                FROM users
                WHERE tax_no IS NOT NULL
                  AND is_active = true
                  AND locale = 'tr'
                ORDER BY created_at DESC;
            """,

            "pending_jobs_by_priority": """
                -- Uses idx_jobs_type_status (composite index)
                SELECT id, type, priority, created_at
                FROM jobs
                WHERE status IN ('pending', 'queued')
                ORDER BY priority DESC, created_at ASC
                LIMIT 50;
            """,

            "user_job_history": """
                -- Uses idx_jobs_user_id
                SELECT j.id, j.type, j.status, j.created_at, j.finished_at
                FROM jobs j
                WHERE j.user_id = $1
                ORDER BY j.created_at DESC
                LIMIT 100;
            """,

            "idempotent_job_lookup": """
                -- Uses idx_jobs_idempotency_key (partial index)
                SELECT id, status, created_at, output_data
                FROM jobs
                WHERE idempotency_key = $1
                LIMIT 1;
            """,

            "overdue_invoices": """
                -- Uses idx_invoices_due_at (partial index for unpaid invoices)
                SELECT i.number, i.amount_cents, i.currency, i.due_at, u.email
                FROM invoices i
                JOIN users u ON i.user_id = u.id
                WHERE i.due_at < NOW()
                  AND i.status NOT IN ('paid', 'cancelled')
                ORDER BY i.due_at ASC;
            """,

            "payment_reconciliation": """
                -- Uses idx_payments_invoice_id and idx_payments_status
                SELECT p.provider_ref, p.amount_cents, p.status, p.processed_at,
                       i.number, i.amount_cents as invoice_amount
                FROM payments p
                JOIN invoices i ON p.invoice_id = i.id
                WHERE p.status = 'completed'
                  AND p.processed_at >= $1
                ORDER BY p.processed_at DESC;
            """,

            "audit_trail_for_entity": """
                -- Uses idx_audit_logs_entity (composite index)
                SELECT action, created_at, payload, user_id
                FROM audit_logs
                WHERE entity_type = $1 AND entity_id = $2
                ORDER BY created_at ASC;
            """,

            "recent_security_events": """
                -- Uses idx_audit_logs_action and idx_audit_logs_created_at
                SELECT action, entity_type, ip_address, created_at, payload
                FROM audit_logs
                WHERE action IN ('auth_failed', 'access_denied', 'privilege_escalation')
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC;
            """,

            "financial_audit_trail": """
                -- Complex query using multiple indexes
                SELECT 
                    al.action,
                    al.entity_type,
                    al.entity_id,
                    al.created_at,
                    al.payload->>'amount_cents' as amount_cents,
                    u.email as user_email
                FROM audit_logs al
                LEFT JOIN users u ON al.user_id = u.id
                WHERE al.entity_type IN ('invoice', 'payment')
                  AND al.created_at >= $1
                  AND al.created_at <= $2
                ORDER BY al.created_at DESC;
            """
        }

    @staticmethod
    def create_idempotency_examples() -> dict[str, Any]:
        """
        Provide examples of idempotent operations and their validation.
        """

        return {
            "job_creation_semantics": {
                "description": "Demonstrates idempotent job creation using idempotency keys",
                "example": {
                    "idempotency_key": "user123_cad_generation_20250115_bracket001",
                    "operation": "cad_generate",
                    "expected_behavior": [
                        "First request: Creates new job, returns job_id",
                        "Duplicate request: Returns existing job_id, no new job created",
                        "Status check: Same idempotency_key always returns same result"
                    ]
                }
            },

            "invoice_creation_semantics": {
                "description": "Demonstrates idempotent invoice creation with financial precision",
                "example": {
                    "idempotency_key": "monthly_billing_user123_202501",
                    "operation": "invoice_create",
                    "amount_validation": {
                        "input_decimal": "1234.56",
                        "stored_cents": 123456,
                        "retrieved_decimal": "1234.56",
                        "precision_maintained": True
                    }
                }
            },

            "payment_processing_semantics": {
                "description": "Demonstrates idempotent payment processing with provider reconciliation",
                "example": {
                    "provider_ref": "stripe_pi_1AbCdE2fGhIjKlMn",
                    "duplicate_handling": [
                        "First webhook: Process payment, update invoice status",
                        "Duplicate webhook: Ignore, return existing result",
                        "Status remains consistent across duplicate requests"
                    ]
                }
            }
        }


# Export main fixture class
__all__ = ['EnterpriseTestFixtures']
