# Canonical JSON Specification

## Overview
This document defines the canonical JSON serialization rules for ensuring consistent, deterministic JSON representations. This is critical for audit hash-chain integrity, idempotency checks, and data verification.

## Purpose
Canonical JSON ensures that the same data always produces the same JSON string, enabling:
- Cryptographic hash verification
- Audit trail integrity via hash chains
- Idempotency key generation
- Data deduplication
- Signature verification

## Canonical JSON Rules

### 1. Object Key Ordering
Object keys MUST be sorted lexicographically (alphabetically) in ascending order.

```json
// Canonical
{
  "age": 30,
  "email": "user@example.com",
  "id": 1,
  "name": "John Doe"
}

// Non-canonical
{
  "name": "John Doe",
  "id": 1,
  "age": 30,
  "email": "user@example.com"
}
```

### 2. No Whitespace
All unnecessary whitespace MUST be removed. No spaces, tabs, or newlines except within string values.

```json
// Canonical
{"id":1,"name":"John Doe","active":true}

// Non-canonical
{
  "id": 1,
  "name": "John Doe",
  "active": true
}
```

### 3. Number Representation
Numbers MUST follow these rules:
- No leading zeros (except "0" itself)
- No trailing decimal point
- No unnecessary decimal zeros
- Use scientific notation only when necessary
- Negative zero is normalized to zero

```json
// Canonical
{"price":10,"quantity":1,"rate":0.5,"large":1e10}

// Non-canonical
{"price":10.0,"quantity":01,"rate":0.50,"large":10000000000}
```

### 4. String Escaping
Strings MUST use minimal escaping:
- Escape only: `"`, `\`, and control characters (U+0000 to U+001F)
- Use `\uXXXX` for control characters
- Do not escape forward slash `/`

```json
// Canonical
{"path":"C:\\Users\\file.txt","quote":"She said \"Hello\"","tab":"Line1\u0009Line2"}

// Non-canonical
{"path":"C:\/Users\/file.txt","quote":"She said \u0022Hello\u0022","tab":"Line1\tLine2"}
```

### 5. Boolean and Null Values
Boolean and null values MUST be lowercase.

```json
// Canonical
{"active":true,"deleted":false,"parent":null}

// Non-canonical
{"active":True,"deleted":FALSE,"parent":NULL}
```

### 6. Array Formatting
Arrays MUST NOT have trailing commas and MUST preserve element order.

```json
// Canonical
{"items":[1,2,3],"tags":["cad","cam","cnc"]}

// Non-canonical
{"items":[1,2,3,],"tags":["cad","cam","cnc",]}
```

### 7. Unicode Normalization
All strings MUST be in Unicode Normalization Form C (NFC).

```json
// Canonical (é as single character U+00E9)
{"name":"José"}

// Non-canonical (é as e + combining accent U+0065 U+0301)
{"name":"José"}
```

## Implementation

### Python Implementation
```python
import json
import hashlib
from typing import Any, Dict
from decimal import Decimal
from datetime import datetime, date
from uuid import UUID

def canonical_json(data: Any) -> str:
    """
    Convert data to canonical JSON string.
    
    Args:
        data: Python object to serialize
        
    Returns:
        Canonical JSON string
    """
    return json.dumps(
        data,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        default=_json_serializer
    )

def _json_serializer(obj: Any) -> Any:
    """
    Custom JSON serializer for special types.
    """
    if isinstance(obj, datetime):
        return obj.isoformat() + 'Z'
    elif isinstance(obj, date):
        return obj.isoformat()
    elif isinstance(obj, Decimal):
        return float(obj)
    elif isinstance(obj, UUID):
        return str(obj)
    elif isinstance(obj, bytes):
        return obj.hex()
    elif hasattr(obj, '__dict__'):
        return obj.__dict__
    else:
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

def compute_hash(data: Any) -> str:
    """
    Compute SHA256 hash of canonical JSON.
    
    Args:
        data: Python object to hash
        
    Returns:
        Hex-encoded SHA256 hash
    """
    canonical = canonical_json(data)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()

def verify_hash(data: Any, expected_hash: str) -> bool:
    """
    Verify data matches expected hash.
    
    Args:
        data: Python object to verify
        expected_hash: Expected SHA256 hash
        
    Returns:
        True if hash matches
    """
    return compute_hash(data) == expected_hash
```

### TypeScript Implementation
```typescript
import crypto from 'crypto';

/**
 * Convert object to canonical JSON string
 */
export function canonicalJSON(data: any): string {
  return JSON.stringify(data, replacer, 0);
}

/**
 * Custom replacer for JSON.stringify
 */
function replacer(key: string, value: any): any {
  // Handle special types
  if (value instanceof Date) {
    return value.toISOString();
  }
  
  // Sort object keys
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return Object.keys(value)
      .sort()
      .reduce((sorted: any, key: string) => {
        sorted[key] = value[key];
        return sorted;
      }, {});
  }
  
  return value;
}

/**
 * Compute SHA256 hash of canonical JSON
 */
export function computeHash(data: any): string {
  const canonical = canonicalJSON(data);
  return crypto
    .createHash('sha256')
    .update(canonical, 'utf8')
    .digest('hex');
}

/**
 * Verify data matches expected hash
 */
export function verifyHash(data: any, expectedHash: string): boolean {
  return computeHash(data) === expectedHash;
}
```

### SQL/PostgreSQL Function
```sql
-- Create canonical JSON function
CREATE OR REPLACE FUNCTION canonical_json(data JSONB)
RETURNS TEXT AS $$
DECLARE
    result TEXT;
BEGIN
    -- PostgreSQL's jsonb type already stores in canonical form
    -- Keys are sorted, whitespace removed, duplicates eliminated
    result := data::TEXT;
    
    -- Remove spaces after colons and commas for compact form
    result := REPLACE(result, ': ', ':');
    result := REPLACE(result, ', ', ',');
    
    RETURN result;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Create hash computation function
CREATE OR REPLACE FUNCTION compute_json_hash(data JSONB)
RETURNS TEXT AS $$
BEGIN
    RETURN encode(
        digest(canonical_json(data), 'sha256'),
        'hex'
    );
END;
$$ LANGUAGE plpgsql IMMUTABLE;

-- Example usage in audit trigger
CREATE OR REPLACE FUNCTION audit_hash_chain()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
    audit_data JSONB;
BEGIN
    -- Get previous hash
    SELECT chain_hash INTO prev_hash
    FROM audit_logs
    ORDER BY id DESC
    LIMIT 1;
    
    -- Default to genesis hash if no previous
    IF prev_hash IS NULL THEN
        prev_hash := REPEAT('0', 64);
    END IF;
    
    -- Build audit data
    audit_data := jsonb_build_object(
        'action', NEW.action,
        'entity_type', NEW.entity_type,
        'entity_id', NEW.entity_id,
        'entity_data', NEW.entity_data,
        'changes', NEW.changes,
        'user_id', NEW.user_id,
        'ip_address', NEW.ip_address::TEXT,
        'created_at', NEW.created_at
    );
    
    -- Compute chain hash
    NEW.prev_chain_hash := prev_hash;
    NEW.chain_hash := encode(
        digest(
            prev_hash || canonical_json(audit_data),
            'sha256'
        ),
        'hex'
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

## Use Cases

### 1. Audit Trail Hash Chain
Ensures audit log integrity by chaining entries together.

```python
def create_audit_entry(
    action: str,
    entity_type: str,
    entity_id: int,
    changes: Dict,
    user_id: int,
    prev_hash: str
) -> Dict:
    """Create audit log entry with hash chain."""
    
    # Build audit data
    audit_data = {
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "changes": changes,
        "user_id": user_id,
        "timestamp": datetime.utcnow().isoformat() + 'Z'
    }
    
    # Compute chain hash
    canonical = canonical_json(audit_data)
    chain_input = prev_hash + canonical
    chain_hash = hashlib.sha256(chain_input.encode()).hexdigest()
    
    return {
        **audit_data,
        "prev_chain_hash": prev_hash,
        "chain_hash": chain_hash
    }
```

### 2. Idempotency Key Generation
Generate deterministic keys for duplicate request detection.

```python
def generate_idempotency_key(request_data: Dict) -> str:
    """Generate idempotency key from request data."""
    
    # Extract relevant fields
    key_data = {
        "user_id": request_data.get("user_id"),
        "operation": request_data.get("operation"),
        "params": request_data.get("params"),
        # Exclude timestamp and request ID
    }
    
    # Generate deterministic key
    return compute_hash(key_data)
```

### 3. Data Deduplication
Identify duplicate files or data.

```python
def deduplicate_models(models: List[Dict]) -> List[Dict]:
    """Remove duplicate models based on content hash."""
    
    seen_hashes = set()
    unique_models = []
    
    for model in models:
        # Compute content hash
        content_hash = compute_hash({
            "geometry": model["geometry"],
            "materials": model["materials"],
            "metadata": model["metadata"]
        })
        
        if content_hash not in seen_hashes:
            seen_hashes.add(content_hash)
            unique_models.append(model)
    
    return unique_models
```

### 4. Change Detection
Detect if data has been modified.

```python
def has_changed(old_data: Dict, new_data: Dict) -> bool:
    """Check if data has changed."""
    return compute_hash(old_data) != compute_hash(new_data)

def get_changes(old_data: Dict, new_data: Dict) -> Dict:
    """Get specific fields that changed."""
    changes = {}
    
    for key in set(old_data.keys()) | set(new_data.keys()):
        old_value = old_data.get(key)
        new_value = new_data.get(key)
        
        if compute_hash(old_value) != compute_hash(new_value):
            changes[key] = {
                "old": old_value,
                "new": new_value
            }
    
    return changes
```

## Validation

### Schema Validation
Ensure data conforms to expected structure before canonicalization.

```python
from jsonschema import validate

def validate_and_canonicalize(data: Dict, schema: Dict) -> str:
    """Validate data against schema and return canonical JSON."""
    
    # Validate structure
    validate(instance=data, schema=schema)
    
    # Return canonical form
    return canonical_json(data)
```

### Hash Chain Validation
Verify integrity of hash chain.

```python
def verify_hash_chain(entries: List[Dict]) -> bool:
    """Verify integrity of audit hash chain."""
    
    prev_hash = "0" * 64  # Genesis hash
    
    for entry in entries:
        # Verify previous hash matches
        if entry["prev_chain_hash"] != prev_hash:
            return False
        
        # Recompute and verify chain hash
        audit_data = {k: v for k, v in entry.items() 
                     if k not in ["prev_chain_hash", "chain_hash"]}
        
        canonical = canonical_json(audit_data)
        expected_hash = hashlib.sha256(
            (prev_hash + canonical).encode()
        ).hexdigest()
        
        if entry["chain_hash"] != expected_hash:
            return False
        
        prev_hash = entry["chain_hash"]
    
    return True
```

## Performance Considerations

1. **Caching**: Cache canonical representations for frequently accessed data
2. **Indexing**: Store hashes in indexed columns for fast lookups
3. **Batch Processing**: Process multiple items together to amortize overhead
4. **Async Computation**: Compute hashes asynchronously for large datasets

## Security Considerations

1. **Hash Algorithm**: Use SHA256 minimum, consider SHA3 for future-proofing
2. **Timing Attacks**: Use constant-time comparison for hash verification
3. **Salt/Nonce**: Add salt for non-public data to prevent rainbow tables
4. **Key Derivation**: Use proper KDF (PBKDF2, Argon2) for password-based hashes

## Best Practices

1. **Immutable Fields**: Never modify fields used in hash computation
2. **Version Control**: Version your canonicalization rules
3. **Migration Path**: Plan for algorithm upgrades
4. **Documentation**: Document which fields are included/excluded
5. **Testing**: Comprehensive tests for edge cases
6. **Monitoring**: Monitor hash verification failures