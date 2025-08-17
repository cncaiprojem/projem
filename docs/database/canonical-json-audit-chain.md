# Canonical JSON and Audit Chain Documentation
**Task 2.10: Ultra Enterprise Model Parity and Documentation**

## Overview

This document describes the canonical JSON implementation and cryptographic audit chain system for the FreeCAD CNC/CAM/CAD Production Platform. The system ensures immutable audit trails with banking-level integrity and Turkish regulatory compliance.

## Canonical JSON Rules

### Core Principles

1. **Deterministic Serialization**: Same data always produces identical JSON
2. **Cryptographic Integrity**: Suitable for hash chain calculations
3. **Cross-Language Compatibility**: Works consistently across different systems
4. **Regulatory Compliance**: Meets Turkish audit requirements (KVKV/GDPR)

### Serialization Rules

#### 1. Object Key Ordering
- All object keys MUST be sorted alphabetically
- Unicode sorting using UTF-8 byte order
- Case-sensitive sorting (uppercase before lowercase)

```python
# ✅ CORRECT: Keys sorted alphabetically
{"action": "create", "entity_id": "123", "timestamp": "2025-01-15T10:30:00Z"}

# ❌ WRONG: Keys not sorted
{"timestamp": "2025-01-15T10:30:00Z", "action": "create", "entity_id": "123"}
```

#### 2. Whitespace Elimination
- No spaces after separators (`:` and `,`)
- Compact representation for consistent hashing
- Unicode characters escaped as `\\uXXXX`

```python
# ✅ CORRECT: Compact format
{"action":"create","user_id":123}

# ❌ WRONG: Extra whitespace
{"action": "create", "user_id": 123}
```

#### 3. Data Type Normalization

**Timestamps**:
- Always converted to UTC ISO 8601 format
- Timezone suffix: `Z` (not `+00:00`)
- Microseconds excluded for consistency

```python
# ✅ CORRECT: UTC with Z suffix
"2025-01-15T10:30:00Z"

# ❌ WRONG: Local timezone or microseconds
"2025-01-15T13:30:00+03:00"
"2025-01-15T10:30:00.123456Z"
```

**Decimal Numbers**:
- Financial amounts: Convert to string representation
- Preserves precision for banking calculations
- No scientific notation

```python
# ✅ CORRECT: String representation
{"amount": "123.45", "tax_rate": "20.00"}

# ❌ WRONG: Float representation
{"amount": 123.45, "tax_rate": 20.0}
```

**UUIDs**:
- Always converted to lowercase string format
- Standard hyphenated format: `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`

```python
# ✅ CORRECT: Lowercase hyphenated
"550e8400-e29b-41d4-a716-446655440000"

# ❌ WRONG: Uppercase or no hyphens
"550E8400-E29B-41D4-A716-446655440000"
"550e8400e29b41d4a716446655440000"
```

**None/Null Values**:
- Python `None` becomes JSON `null`
- Empty strings remain as `""`
- Empty objects remain as `{}`

#### 4. Field Exclusion Rules

**Automatic Exclusions**:
- Fields starting with underscore (`_private_field`)
- Computed properties without backing data
- Circular references

**Security Exclusions**:
- Password hashes: `password_hash`
- Tokens: `refresh_token_hash`, `access_token_jti`
- Cryptographic material: `private_key`, `secret_key`

### Implementation Example

```python
from app.helpers.canonical_json import CanonicalJSONEncoder

# Create audit record
audit_data = {
    "action": "invoice_create",
    "user_id": 123,
    "entity_type": "invoice",
    "entity_id": "INV-2025-001",
    "timestamp": datetime.now(timezone.utc),
    "amount": Decimal("1234.56"),
    "changes": {
        "status": {"old": None, "new": "draft"},
        "total": {"old": 0, "new": 123456}  # amount in cents
    }
}

# Generate canonical JSON
canonical_json = CanonicalJSONEncoder.canonicalize(audit_data)
print(canonical_json)
# Output: {"action":"invoice_create","amount":"1234.56","changes":{"status":{"new":"draft","old":null},"total":{"new":123456,"old":0}},"entity_id":"INV-2025-001","entity_type":"invoice","timestamp":"2025-01-15T10:30:00Z","user_id":123}
```

## Audit Chain System

### Cryptographic Hash Chain

The audit chain uses SHA-256 hashing to create an immutable sequence of audit records. Each record's hash depends on the previous record, making tampering detectable.

#### Chain Structure

```
Genesis Record: hash = SHA256(canonical_json)
Record 1: hash = SHA256(previous_hash + ":" + canonical_json)
Record 2: hash = SHA256(previous_hash + ":" + canonical_json)
...
```

#### Hash Chain Verification

```python
from app.helpers.canonical_json import AuditChainManager

# Verify single record
is_valid = AuditChainManager.verify_hash_chain(
    current_hash="abc123...",
    audit_record=audit_data,
    previous_hash="def456..."
)

# Generate new hash
new_hash = AuditChainManager.compute_hash_chain(
    audit_record=audit_data,
    previous_hash="def456..."
)
```

### Audit Record Structure

#### Required Fields
- `action`: Action performed (e.g., "create", "update", "delete")
- `entity_type`: Type of entity (e.g., "user", "invoice", "job")
- `timestamp`: UTC timestamp in ISO 8601 format

#### Optional Fields
- `entity_id`: ID of affected entity
- `entity_data`: Complete entity state after action
- `changes`: Field-level before/after changes
- `user_id`: Acting user ID
- `ip_address`: Client IP address
- `user_agent`: Client user agent
- `session_id`: User session ID
- `metadata`: Additional context data

#### Example Audit Record

```json
{
  "action": "invoice_update",
  "entity_type": "invoice",
  "entity_id": "INV-2025-001",
  "timestamp": "2025-01-15T10:30:00Z",
  "user_id": 123,
  "ip_address": "192.168.1.100",
  "changes": {
    "status": {
      "old": "draft",
      "new": "sent"
    },
    "issued_at": {
      "old": null,
      "new": "2025-01-15T10:30:00Z"
    }
  },
  "metadata": {
    "invoice_number": "INV-2025-001",
    "customer_email": "customer@example.com",
    "notification_sent": true
  }
}
```

### Chain Integrity Verification

#### Verification Process

1. **Individual Record Verification**:
   - Recompute hash using canonical JSON + previous hash
   - Compare with stored hash value
   - Verify hash format (64-character lowercase hex)

2. **Chain Continuity Verification**:
   - Verify each record's `prev_chain_hash` matches previous record's `chain_hash`
   - Check for gaps in the chain
   - Validate chronological ordering

3. **Genesis Record Verification**:
   - First record has `prev_chain_hash = NULL`
   - Hash computed without previous hash prefix

#### Verification Example

```python
def verify_audit_chain(audit_records):
    """Verify complete audit chain integrity."""
    previous_hash = None
    
    for record in audit_records:
        # Reconstruct audit data (exclude hash fields)
        audit_data = {k: v for k, v in record.items() 
                     if k not in ['chain_hash', 'prev_chain_hash']}
        
        # Verify hash
        expected_hash = AuditChainManager.compute_hash_chain(
            audit_data, previous_hash
        )
        
        if expected_hash != record['chain_hash']:
            raise IntegrityError(f"Hash mismatch for record {record['id']}")
        
        # Verify chain linkage
        if record['prev_chain_hash'] != previous_hash:
            raise IntegrityError(f"Chain break at record {record['id']}")
        
        previous_hash = record['chain_hash']
    
    return True
```

## Turkish Regulatory Compliance

### KVKV (Turkish GDPR) Requirements

1. **Data Subject Rights**:
   - Audit trail for data access requests
   - Deletion tracking (right to be forgotten)
   - Consent change tracking

2. **Data Processing Justification**:
   - Legal basis recorded in audit metadata
   - Processing purpose documentation
   - Data retention period tracking

### Financial Compliance (Türkiye)

1. **Invoice Audit Requirements**:
   - Complete audit trail for all financial transactions
   - Tax calculation audit (KDV - Turkish VAT)
   - Currency exchange rate tracking

2. **Banking Integration**:
   - Payment verification chains
   - Turkish bank account validation (IBAN TR)
   - Central Bank reporting compliance

## Sample Helper Functions

### 1. Invoice Creation Audit

```python
def audit_invoice_creation(invoice, user, session):
    """Create audit record for invoice creation."""
    
    # Sanitize invoice data for audit
    invoice_data = AuditChainManager.sanitize_for_audit(
        invoice.to_dict()
    )
    
    # Create audit record
    audit_record = AuditChainManager.create_audit_record(
        action="invoice_create",
        entity_type="invoice",
        entity_id=invoice.id,
        entity_data=invoice_data,
        user_id=user.id,
        ip_address=session.ip_address,
        user_agent=session.user_agent,
        session_id=session.id,
        metadata={
            "invoice_number": invoice.number,
            "amount_cents": invoice.amount_cents,
            "currency": invoice.currency.value,
            "turkish_tax_compliance": True
        }
    )
    
    return audit_record
```

### 2. User Data Change Tracking

```python
def audit_user_update(old_user_data, new_user_data, user, session):
    """Create audit record for user data changes."""
    
    # Calculate field-level changes
    changes = AuditChainManager.create_field_changes(
        old_values=old_user_data,
        new_values=new_user_data,
        exclude_fields={'password_hash', 'updated_at'}
    )
    
    # Only create audit record if there are actual changes
    if changes:
        audit_record = AuditChainManager.create_audit_record(
            action="user_update",
            entity_type="user",
            entity_id=new_user_data['id'],
            changes=changes,
            user_id=user.id,
            ip_address=session.ip_address,
            metadata={
                "kvkv_compliance": True,
                "data_subject_notification": True
            }
        )
        
        return audit_record
    
    return None
```

### 3. Financial Transaction Audit

```python
def audit_payment_processing(payment, invoice, user, session):
    """Create comprehensive audit for payment processing."""
    
    # Multi-record audit for complex transaction
    audit_records = []
    
    # 1. Payment creation
    payment_audit = AuditChainManager.create_audit_record(
        action="payment_create",
        entity_type="payment",
        entity_id=payment.id,
        entity_data=AuditChainManager.sanitize_for_audit(payment.to_dict()),
        user_id=user.id,
        ip_address=session.ip_address,
        metadata={
            "invoice_id": invoice.id,
            "amount_cents": payment.amount_cents,
            "currency": payment.currency.value,
            "provider": payment.provider,
            "turkish_financial_compliance": True
        }
    )
    audit_records.append(payment_audit)
    
    # 2. Invoice status update
    if payment.status == PaymentStatus.COMPLETED:
        invoice_audit = AuditChainManager.create_audit_record(
            action="invoice_payment_received",
            entity_type="invoice",
            entity_id=invoice.id,
            changes={
                "status": {
                    "old": invoice.status.value,
                    "new": "paid" if invoice.is_fully_paid else "partial"
                }
            },
            user_id=user.id,
            metadata={
                "payment_id": payment.id,
                "total_paid_cents": invoice.paid_amount_cents,
                "balance_due_cents": invoice.balance_due_cents
            }
        )
        audit_records.append(invoice_audit)
    
    return audit_records
```

## Security Considerations

### Hash Chain Security

1. **Hash Algorithm**: SHA-256 for cryptographic security
2. **Salt/Nonce**: Not used to maintain deterministic hashing
3. **Key Management**: No encryption keys - relies on hash integrity
4. **Collision Resistance**: SHA-256 provides adequate protection

### Data Protection

1. **Sensitive Data Exclusion**: Automatically sanitized from audit records
2. **Access Control**: Audit logs require special permissions to view
3. **Retention Policy**: Audit records retained per legal requirements
4. **Backup Integrity**: Audit chain verified during backup/restore

### Compliance Monitoring

1. **Chain Verification**: Automated daily integrity checks
2. **Anomaly Detection**: Unexpected chain breaks trigger alerts
3. **Regulatory Reporting**: Automated compliance report generation
4. **Audit Log Export**: Support for regulatory authority requests

## Performance Considerations

### Optimization Strategies

1. **Batch Processing**: Multiple audit records in single transaction
2. **Async Processing**: Hash computation in background tasks
3. **Index Optimization**: Database indexes on hash fields and timestamps
4. **Archival Strategy**: Old audit records moved to cold storage

### Monitoring Metrics

1. **Hash Computation Time**: Track performance of canonical JSON generation
2. **Chain Verification Speed**: Monitor integrity check performance
3. **Storage Growth**: Track audit log storage requirements
4. **Query Performance**: Monitor audit log search/retrieval speed

## Migration and Rollback Strategy

### Chain Initialization

```sql
-- Initialize audit chain with genesis record
INSERT INTO audit_logs (
    action, entity_type, timestamp, 
    chain_hash, prev_chain_hash, 
    payload
) VALUES (
    'system_init', 'system', NOW(),
    '0000000000000000000000000000000000000000000000000000000000000000',
    NULL,
    '{"action":"system_init","entity_type":"system","timestamp":"2025-01-15T10:30:00Z"}'
);
```

### Chain Migration

1. **Schema Changes**: Preserve existing hash chain during migrations
2. **Data Migration**: Maintain chain integrity during data transformations
3. **Rollback Protection**: Verify chain integrity before and after migrations
4. **Backup Strategy**: Complete chain backup before major changes

This documentation ensures that the canonical JSON and audit chain system provides enterprise-grade data integrity with full Turkish regulatory compliance.