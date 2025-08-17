# Audit Hash-Chain Specification

## Overview
This document specifies the cryptographic hash-chain implementation for the audit trail system. The hash-chain ensures tamper-evident logging where any modification to historical audit records can be detected.

## Hash-Chain Architecture

### Chain Structure
Each audit log entry contains:
- `id`: Sequential identifier
- `chain_hash`: SHA256 hash of current entry
- `prev_chain_hash`: Hash of previous entry
- `payload`: Audit data (action, entity, changes, etc.)

### Hash Computation
```
chain_hash = SHA256(prev_chain_hash || canonical_json(payload))
```

Where:
- `||` denotes concatenation
- `canonical_json()` produces deterministic JSON representation
- Genesis block uses `prev_chain_hash = "0" * 64`

## Implementation

### Database Schema
```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(100) NOT NULL,
    entity_type VARCHAR(50) NOT NULL,
    entity_id INTEGER,
    entity_data JSONB,
    changes JSONB,
    ip_address INET,
    user_agent TEXT,
    session_id INTEGER REFERENCES sessions(id) ON DELETE SET NULL,
    chain_hash CHAR(64) UNIQUE NOT NULL,
    prev_chain_hash CHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    
    -- Indexes
    INDEX idx_audit_logs_chain_hash (chain_hash),
    INDEX idx_audit_logs_created_at (created_at DESC)
);
```

### PostgreSQL Trigger Implementation
```sql
CREATE OR REPLACE FUNCTION compute_audit_chain_hash()
RETURNS TRIGGER AS $$
DECLARE
    prev_hash TEXT;
    payload JSONB;
    canonical TEXT;
BEGIN
    -- Get previous entry's hash
    SELECT chain_hash INTO prev_hash
    FROM audit_logs
    WHERE id < NEW.id
    ORDER BY id DESC
    LIMIT 1;
    
    -- Use genesis hash if first entry
    IF prev_hash IS NULL THEN
        prev_hash := REPEAT('0', 64);
    END IF;
    
    -- Build payload
    payload := jsonb_build_object(
        'id', NEW.id,
        'user_id', NEW.user_id,
        'action', NEW.action,
        'entity_type', NEW.entity_type,
        'entity_id', NEW.entity_id,
        'entity_data', NEW.entity_data,
        'changes', NEW.changes,
        'ip_address', COALESCE(NEW.ip_address::TEXT, ''),
        'user_agent', COALESCE(NEW.user_agent, ''),
        'session_id', NEW.session_id,
        'created_at', TO_CHAR(NEW.created_at, 'YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
    );
    
    -- Get canonical JSON representation
    canonical := canonical_json(payload);
    
    -- Compute chain hash
    NEW.prev_chain_hash := prev_hash;
    NEW.chain_hash := encode(
        digest(prev_hash || canonical, 'sha256'),
        'hex'
    );
    
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Apply trigger before insert
CREATE TRIGGER audit_chain_hash_trigger
BEFORE INSERT ON audit_logs
FOR EACH ROW
EXECUTE FUNCTION compute_audit_chain_hash();
```

### Python Implementation
```python
import hashlib
import json
from datetime import datetime
from typing import Dict, Optional, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

class AuditChain:
    """Manages audit trail hash-chain integrity."""
    
    GENESIS_HASH = "0" * 64
    
    @staticmethod
    def canonical_json(data: Dict[str, Any]) -> str:
        """Convert data to canonical JSON representation."""
        return json.dumps(
            data,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            default=str
        )
    
    @staticmethod
    def compute_hash(prev_hash: str, payload: Dict[str, Any]) -> str:
        """Compute chain hash for audit entry."""
        canonical = AuditChain.canonical_json(payload)
        chain_input = prev_hash + canonical
        return hashlib.sha256(chain_input.encode('utf-8')).hexdigest()
    
    @classmethod
    async def create_entry(
        cls,
        session: AsyncSession,
        user_id: Optional[int],
        action: str,
        entity_type: str,
        entity_id: Optional[int],
        entity_data: Optional[Dict],
        changes: Optional[Dict],
        ip_address: Optional[str],
        user_agent: Optional[str],
        session_id: Optional[int]
    ) -> Dict[str, Any]:
        """Create a new audit log entry with hash chain."""
        
        # Get previous hash
        result = await session.execute(
            select(AuditLog.chain_hash)
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        prev_entry = result.scalar_one_or_none()
        prev_hash = prev_entry if prev_entry else cls.GENESIS_HASH
        
        # Build payload
        now = datetime.utcnow()
        payload = {
            'user_id': user_id,
            'action': action,
            'entity_type': entity_type,
            'entity_id': entity_id,
            'entity_data': entity_data or {},
            'changes': changes or {},
            'ip_address': ip_address or '',
            'user_agent': user_agent or '',
            'session_id': session_id,
            'created_at': now.isoformat() + 'Z'
        }
        
        # Compute chain hash
        chain_hash = cls.compute_hash(prev_hash, payload)
        
        # Create audit entry
        audit_entry = AuditLog(
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_data=entity_data,
            changes=changes,
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            chain_hash=chain_hash,
            prev_chain_hash=prev_hash,
            created_at=now
        )
        
        session.add(audit_entry)
        await session.flush()
        
        return {
            'id': audit_entry.id,
            'chain_hash': chain_hash,
            'prev_chain_hash': prev_hash,
            **payload
        }
    
    @classmethod
    async def verify_chain(
        cls,
        session: AsyncSession,
        start_id: Optional[int] = None,
        end_id: Optional[int] = None
    ) -> tuple[bool, Optional[int]]:
        """
        Verify hash chain integrity.
        
        Returns:
            (is_valid, first_invalid_id)
        """
        query = select(AuditLog).order_by(AuditLog.id)
        
        if start_id:
            query = query.where(AuditLog.id >= start_id)
        if end_id:
            query = query.where(AuditLog.id <= end_id)
        
        result = await session.execute(query)
        entries = result.scalars().all()
        
        if not entries:
            return True, None
        
        # Verify first entry
        first = entries[0]
        if first.id == 1 and first.prev_chain_hash != cls.GENESIS_HASH:
            return False, first.id
        
        # Verify chain continuity
        for i, entry in enumerate(entries):
            # Build payload from stored data
            payload = {
                'id': entry.id,
                'user_id': entry.user_id,
                'action': entry.action,
                'entity_type': entry.entity_type,
                'entity_id': entry.entity_id,
                'entity_data': entry.entity_data or {},
                'changes': entry.changes or {},
                'ip_address': entry.ip_address or '',
                'user_agent': entry.user_agent or '',
                'session_id': entry.session_id,
                'created_at': entry.created_at.isoformat() + 'Z'
            }
            
            # Recompute hash
            expected_hash = cls.compute_hash(entry.prev_chain_hash, payload)
            
            if entry.chain_hash != expected_hash:
                return False, entry.id
            
            # Verify chain continuity
            if i > 0 and entry.prev_chain_hash != entries[i-1].chain_hash:
                return False, entry.id
        
        return True, None
```

## Verification Procedures

### Periodic Verification
```python
async def periodic_chain_verification(session: AsyncSession):
    """Run periodic hash chain verification."""
    
    # Get last verified position
    last_verified = await get_last_verified_id(session)
    
    # Verify chain from last position
    is_valid, invalid_id = await AuditChain.verify_chain(
        session,
        start_id=last_verified
    )
    
    if not is_valid:
        # Alert on chain corruption
        await create_security_alert(
            session,
            event_type='audit_chain_corruption',
            severity='critical',
            details={
                'invalid_entry_id': invalid_id,
                'last_verified_id': last_verified
            }
        )
        return False
    
    # Update verification checkpoint
    await update_last_verified_id(session, get_max_audit_id())
    return True
```

### Manual Verification
```sql
-- Verify specific range
WITH chain_check AS (
    SELECT 
        id,
        chain_hash,
        prev_chain_hash,
        LAG(chain_hash) OVER (ORDER BY id) AS actual_prev_hash,
        -- Recompute hash (simplified, actual needs canonical JSON)
        encode(
            digest(
                prev_chain_hash || 
                jsonb_build_object(
                    'id', id,
                    'action', action,
                    'entity_type', entity_type,
                    'entity_id', entity_id,
                    'created_at', created_at
                )::text,
                'sha256'
            ),
            'hex'
        ) AS computed_hash
    FROM audit_logs
    WHERE id BETWEEN 1000 AND 2000
)
SELECT 
    id,
    chain_hash = computed_hash AS hash_valid,
    prev_chain_hash = COALESCE(actual_prev_hash, REPEAT('0', 64)) AS chain_valid
FROM chain_check
WHERE 
    chain_hash != computed_hash OR
    prev_chain_hash != COALESCE(actual_prev_hash, REPEAT('0', 64));
```

## Security Properties

### Tamper Evidence
Any modification to historical records will break the chain:
1. Changing audit data invalidates the chain_hash
2. Deleting entries breaks chain continuity
3. Reordering entries breaks prev_chain_hash references

### Attack Scenarios

#### 1. Data Modification
- **Attack**: Modify `entity_data` in historical record
- **Detection**: Recomputed hash won't match stored `chain_hash`
- **Impact**: Chain verification fails at modified entry

#### 2. Entry Deletion
- **Attack**: Delete audit entry ID 500
- **Detection**: Entry 501's `prev_chain_hash` references non-existent hash
- **Impact**: Chain break detected at entry 501

#### 3. Entry Insertion
- **Attack**: Insert fake entry between ID 500 and 501
- **Detection**: Fake entry's hash not referenced by entry 501
- **Impact**: Chain discontinuity detected

#### 4. Hash Forgery
- **Attack**: Modify entry and update its hash
- **Detection**: Next entry's `prev_chain_hash` won't match
- **Impact**: Requires updating all subsequent hashes (computationally infeasible)

## Performance Optimization

### Batch Verification
```python
async def batch_verify_chain(
    session: AsyncSession,
    batch_size: int = 1000
) -> Dict[str, Any]:
    """Verify chain in batches for performance."""
    
    total_count = await session.scalar(select(func.count(AuditLog.id)))
    batches_verified = 0
    errors = []
    
    for offset in range(0, total_count, batch_size):
        batch_valid, invalid_id = await AuditChain.verify_chain(
            session,
            start_id=offset,
            end_id=offset + batch_size - 1
        )
        
        if not batch_valid:
            errors.append({
                'batch_start': offset,
                'invalid_id': invalid_id
            })
        
        batches_verified += 1
    
    return {
        'total_entries': total_count,
        'batches_verified': batches_verified,
        'is_valid': len(errors) == 0,
        'errors': errors
    }
```

### Checkpoint System
Store verification checkpoints to avoid re-verifying entire chain:

```sql
CREATE TABLE audit_checkpoints (
    id SERIAL PRIMARY KEY,
    audit_id INTEGER NOT NULL,
    chain_hash CHAR(64) NOT NULL,
    verified_at TIMESTAMP NOT NULL DEFAULT NOW(),
    verified_by INTEGER REFERENCES users(id),
    verification_hash CHAR(64) NOT NULL -- Hash of verification process
);

-- Index for fast checkpoint lookup
CREATE INDEX idx_audit_checkpoints_audit_id ON audit_checkpoints(audit_id DESC);
```

## Monitoring & Alerts

### Real-time Monitoring
```python
class AuditChainMonitor:
    """Monitor audit chain integrity in real-time."""
    
    async def monitor_insertions(self, session: AsyncSession):
        """Monitor new audit insertions for chain validity."""
        
        async for entry in watch_audit_insertions():
            # Verify entry's chain hash
            expected_prev = await get_previous_hash(session, entry.id)
            
            if entry.prev_chain_hash != expected_prev:
                await alert_chain_break(entry.id, 'invalid_prev_hash')
            
            # Verify computed hash
            computed = AuditChain.compute_hash(
                entry.prev_chain_hash,
                extract_payload(entry)
            )
            
            if entry.chain_hash != computed:
                await alert_chain_break(entry.id, 'invalid_chain_hash')
```

### Alert Thresholds
- **Critical**: Any chain break detected
- **Warning**: Verification taking >5 seconds
- **Info**: Successful periodic verification

## Recovery Procedures

### Chain Break Recovery
1. **Identify Break Point**: Find first invalid entry
2. **Isolate Corrupted Range**: Determine extent of corruption
3. **Backup Preservation**: Archive corrupted data for forensics
4. **Chain Rebuild**: Rebuild chain from last valid checkpoint
5. **Investigation**: Analyze corruption cause
6. **Report Generation**: Document incident

### Backup Strategy
```sql
-- Regular chain backup
CREATE TABLE audit_chain_backup (
    backup_id SERIAL PRIMARY KEY,
    backup_date TIMESTAMP NOT NULL DEFAULT NOW(),
    start_id INTEGER NOT NULL,
    end_id INTEGER NOT NULL,
    entries JSONB NOT NULL, -- Complete audit entries
    chain_verified BOOLEAN NOT NULL,
    backup_hash CHAR(64) NOT NULL -- Hash of backup data
);
```

## Compliance & Reporting

### Regulatory Compliance
- **GDPR**: Immutable audit trail for data processing activities
- **SOC 2**: Cryptographic integrity for audit logs
- **ISO 27001**: Tamper-evident logging requirement
- **PCI DSS**: Secure audit trail maintenance

### Audit Reports
```python
async def generate_audit_report(
    session: AsyncSession,
    start_date: datetime,
    end_date: datetime
) -> Dict[str, Any]:
    """Generate compliance audit report."""
    
    # Verify chain integrity for period
    entries = await get_audit_entries(session, start_date, end_date)
    is_valid, invalid_id = await verify_entries(entries)
    
    # Generate statistics
    stats = {
        'period': {
            'start': start_date.isoformat(),
            'end': end_date.isoformat()
        },
        'total_entries': len(entries),
        'chain_integrity': is_valid,
        'invalid_entry': invalid_id,
        'actions_summary': count_by_action(entries),
        'users_summary': count_by_user(entries),
        'verification_timestamp': datetime.utcnow().isoformat()
    }
    
    # Sign report
    report_hash = compute_hash(stats)
    
    return {
        **stats,
        'report_hash': report_hash,
        'signature': sign_report(report_hash)
    }
```

## Best Practices

1. **Never Update Audit Entries**: Audit logs must be append-only
2. **Regular Verification**: Run chain verification at least daily
3. **Backup Chain State**: Regular backups with verification
4. **Monitor Performance**: Track verification time as chain grows
5. **Archive Old Entries**: Move old entries to cold storage while preserving chain
6. **Document Incidents**: Maintain separate log of chain verification failures
7. **Test Recovery**: Regular disaster recovery drills
8. **Access Control**: Strict permissions on audit tables