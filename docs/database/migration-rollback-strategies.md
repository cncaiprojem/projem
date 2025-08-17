# Migration Rollback Strategies
**Task 2.10: Ultra Enterprise Zero-Downtime Migration and Rollback Strategies**

## Overview

This document outlines comprehensive rollback strategies for each database migration in the FreeCAD CNC/CAM/CAD Production Platform. All strategies are designed for zero-downtime operations with banking-level safety guarantees.

## Core Rollback Principles

### 1. Safety-First Approach
- **Data Preservation**: No data loss during rollbacks
- **Integrity Maintenance**: Audit chain and hash integrity preserved
- **Business Continuity**: Application remains operational during rollbacks
- **Compliance Preservation**: Turkish regulatory compliance maintained

### 2. Rollback Categories

#### Category A: Safe Rollbacks (Zero Risk)
- Adding nullable columns
- Adding indexes
- Adding constraints that don't affect existing data
- Adding new enum values (with proper handling)

#### Category B: Moderate Risk Rollbacks
- Changing column types (with data conversion)
- Adding NOT NULL constraints with defaults
- Modifying indexes (rebuilding required)

#### Category C: High Risk Rollbacks (Requires Careful Planning)
- Dropping columns (data loss risk)
- Changing table structures significantly
- Modifying audit chain structure
- Financial precision changes

## Migration-Specific Rollback Strategies

### Base Revision (20250817_0000)
**Migration**: Enterprise foundation with core table structure
**Risk Level**: Category C (High Risk - Foundation)

#### Rollback Strategy:
```sql
-- CRITICAL: This is the foundation migration
-- Rollback requires complete database restoration from backup

-- 1. Stop all application services
-- 2. Create emergency backup
CREATE DATABASE freecad_emergency_backup_$(date +%Y%m%d_%H%M%S) 
WITH TEMPLATE freecad;

-- 3. Document all dependent data
SELECT table_name, row_count 
FROM (
    SELECT schemaname, tablename as table_name, 
           n_tup_ins - n_tup_del as row_count
    FROM pg_stat_user_tables 
    WHERE schemaname = 'public'
) as table_stats
ORDER BY row_count DESC;

-- 4. Export critical business data
\copy (SELECT * FROM users WHERE is_active = true) TO 'users_backup.csv' CSV HEADER;
\copy (SELECT * FROM invoices WHERE status != 'cancelled') TO 'invoices_backup.csv' CSV HEADER;
\copy (SELECT * FROM audit_logs ORDER BY created_at) TO 'audit_logs_backup.csv' CSV HEADER;

-- 5. Restore from pre-migration backup
-- (This step requires coordinated downtime)
```

**Recovery Time**: 2-4 hours (includes data validation)
**Data Loss Risk**: None if backup is recent
**Business Impact**: Full downtime required

### Task 2.3 Core Tables (20250817_1200)
**Migration**: Core table optimizations and constraints
**Risk Level**: Category B (Moderate Risk)

#### Rollback Strategy:
```sql
-- This migration can be rolled back with careful constraint removal

-- 1. Identify new constraints added
SELECT 
    tc.constraint_name,
    tc.table_name,
    tc.constraint_type
FROM information_schema.table_constraints tc
WHERE tc.table_schema = 'public'
  AND tc.constraint_name LIKE '%task_23%';

-- 2. Remove added constraints in reverse order
-- (Alembic handles this automatically with proper downgrade)

-- 3. Verify data integrity after rollback
SELECT COUNT(*) as total_users FROM users;
SELECT COUNT(*) as total_jobs FROM jobs;
SELECT COUNT(*) as orphaned_jobs 
FROM jobs j LEFT JOIN users u ON j.user_id = u.id 
WHERE u.id IS NULL AND j.user_id IS NOT NULL;

-- 4. Restart application with previous schema
```

**Recovery Time**: 15-30 minutes
**Data Loss Risk**: Very low
**Business Impact**: Brief read-only period (< 5 minutes)

### Operational Tables (20250817_1500)
**Migration**: CAM runs, simulations, and artifacts
**Risk Level**: Category A (Safe)

#### Rollback Strategy:
```sql
-- Safe rollback - only drops tables that were added

-- 1. Check for dependent data
SELECT 
    'cam_runs' as table_name, COUNT(*) as row_count FROM cam_runs
UNION ALL
SELECT 
    'sim_runs' as table_name, COUNT(*) as row_count FROM sim_runs
UNION ALL
SELECT 
    'artefacts' as table_name, COUNT(*) as row_count FROM artefacts;

-- 2. Export dependent data if needed
\copy (SELECT * FROM cam_runs) TO 'cam_runs_backup.csv' CSV HEADER;
\copy (SELECT * FROM sim_runs) TO 'sim_runs_backup.csv' CSV HEADER;
\copy (SELECT * FROM artefacts) TO 'artefacts_backup.csv' CSV HEADER;

-- 3. Execute Alembic downgrade
-- alembic downgrade -1

-- 4. Verify foreign key consistency
SELECT 
    j.id as job_id,
    j.type,
    j.status
FROM jobs j
WHERE j.type IN ('cam_process', 'sim_run')
  AND j.status != 'failed';
```

**Recovery Time**: 5-10 minutes
**Data Loss Risk**: Low (operational data only)
**Business Impact**: Minimal (new features become unavailable)

### Billing Tables (20250817_1600)
**Migration**: Financial precision with amount_cents
**Risk Level**: Category C (High Risk - Financial Data)

#### Rollback Strategy:
```sql
-- CRITICAL: Financial data rollback requires extra precautions

-- 1. Create emergency financial backup
CREATE TABLE invoices_emergency_backup AS 
SELECT * FROM invoices WHERE created_at >= '2025-08-17';

CREATE TABLE payments_emergency_backup AS 
SELECT * FROM payments WHERE created_at >= '2025-08-17';

-- 2. Verify financial integrity before rollback
SELECT 
    currency,
    COUNT(*) as invoice_count,
    SUM(amount_cents) as total_amount_cents,
    SUM(amount_cents::decimal / 100) as total_amount_decimal
FROM invoices 
WHERE status != 'cancelled'
GROUP BY currency;

-- 3. Document payment reconciliation state
SELECT 
    i.number as invoice_number,
    i.amount_cents as invoice_amount,
    COALESCE(SUM(p.amount_cents), 0) as total_payments,
    i.amount_cents - COALESCE(SUM(p.amount_cents), 0) as balance_due
FROM invoices i
LEFT JOIN payments p ON i.id = p.invoice_id AND p.status = 'completed'
GROUP BY i.id, i.number, i.amount_cents
HAVING i.amount_cents - COALESCE(SUM(p.amount_cents), 0) != 0;

-- 4. Execute rollback with validation
-- alembic downgrade -1

-- 5. Post-rollback financial verification
-- Verify all financial calculations remain consistent
```

**Recovery Time**: 30-60 minutes (includes verification)
**Data Loss Risk**: Medium (financial precision may be affected)
**Business Impact**: Payment processing temporarily disabled

### Security & Audit Tables (20250817_1700)
**Migration**: Audit logs and security events
**Risk Level**: Category C (High Risk - Audit Chain)

#### Rollback Strategy:
```sql
-- CRITICAL: Audit chain integrity must be preserved

-- 1. Verify audit chain integrity before rollback
WITH audit_chain_check AS (
    SELECT 
        id,
        chain_hash,
        prev_chain_hash,
        LAG(chain_hash) OVER (ORDER BY created_at) as expected_prev_hash,
        created_at
    FROM audit_logs
    ORDER BY created_at
)
SELECT 
    COUNT(*) as total_records,
    COUNT(CASE WHEN prev_chain_hash = expected_prev_hash THEN 1 END) as valid_links,
    COUNT(CASE WHEN prev_chain_hash != expected_prev_hash THEN 1 END) as broken_links
FROM audit_chain_check
WHERE id > 1; -- Skip genesis record

-- 2. Export complete audit chain
\copy (SELECT * FROM audit_logs ORDER BY created_at) TO 'audit_chain_backup.csv' CSV HEADER;

-- 3. Calculate and store chain verification hash
SELECT 
    'audit_chain_backup_hash' as backup_type,
    sha256(string_agg(chain_hash, '' ORDER BY created_at)) as backup_verification_hash
FROM audit_logs;

-- 4. Execute rollback with audit preservation
-- alembic downgrade -1

-- 5. Restore and verify audit chain
-- (Complex procedure - requires audit chain reconstruction)
```

**Recovery Time**: 1-2 hours (includes audit verification)
**Data Loss Risk**: High (audit history may be affected)
**Business Impact**: Compliance reporting temporarily unavailable

### Global Constraints & Indexes (20250817_1800)
**Migration**: Performance indexes and constraints
**Risk Level**: Category A (Safe)

#### Rollback Strategy:
```sql
-- Safe rollback - only removes performance optimizations

-- 1. Document current query performance
EXPLAIN (ANALYZE, BUFFERS) 
SELECT * FROM users WHERE email = 'test@example.com';

EXPLAIN (ANALYZE, BUFFERS)
SELECT * FROM jobs WHERE status = 'pending' ORDER BY priority DESC;

-- 2. Check index usage statistics
SELECT 
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE schemaname = 'public'
ORDER BY idx_scan DESC;

-- 3. Execute rollback
-- alembic downgrade -1

-- 4. Monitor performance impact after rollback
-- (Performance may degrade, but no data loss)
```

**Recovery Time**: 10-15 minutes
**Data Loss Risk**: None
**Business Impact**: Performance degradation expected

### Seed Data Migration (20250817_1900)
**Migration**: Reference data population
**Risk Level**: Category A (Safe)

#### Rollback Strategy:
```sql
-- Safe rollback - removes reference data only

-- 1. Document reference data before rollback
SELECT 'machines' as table_name, COUNT(*) FROM machines
UNION ALL
SELECT 'materials' as table_name, COUNT(*) FROM materials  
UNION ALL
SELECT 'tools' as table_name, COUNT(*) FROM tools;

-- 2. Check for dependencies on reference data
SELECT 
    j.id,
    j.type,
    j.input_params->>'machine_id' as machine_id
FROM jobs j
WHERE j.input_params->>'machine_id' IS NOT NULL;

-- 3. Execute rollback (removes seed data)
-- alembic downgrade -1

-- 4. Handle dependent data gracefully
-- Application should handle missing reference data
```

**Recovery Time**: 5 minutes
**Data Loss Risk**: Low (reference data only)
**Business Impact**: Some features may be unavailable

## Emergency Rollback Procedures

### Full System Rollback (Last Resort)

```bash
#!/bin/bash
# emergency_rollback.sh - Complete system rollback procedure

# 1. Stop all services immediately
docker compose -f docker-compose.prod.yml down

# 2. Create emergency backup
pg_dump -h postgres -U freecad freecad > emergency_backup_$(date +%Y%m%d_%H%M%S).sql

# 3. Restore from last known good backup
psql -h postgres -U freecad -d freecad -f last_known_good_backup.sql

# 4. Verify system integrity
python scripts/verify_system_integrity.py

# 5. Restart services in safe mode
docker compose -f docker-compose.prod.yml up -d --scale worker=1
```

### Partial Rollback (Specific Migration)

```bash
#!/bin/bash
# partial_rollback.sh - Rollback specific migration

MIGRATION_ID=$1
BACKUP_LABEL="rollback_$(date +%Y%m%d_%H%M%S)"

# 1. Create checkpoint backup
pg_dump -h postgres -U freecad freecad > checkpoint_${BACKUP_LABEL}.sql

# 2. Put application in maintenance mode
curl -X POST http://localhost:8000/admin/maintenance/enable

# 3. Execute migration rollback
cd apps/api && alembic downgrade $MIGRATION_ID

# 4. Verify database consistency
python scripts/verify_migration_integrity.py

# 5. Remove maintenance mode
curl -X POST http://localhost:8000/admin/maintenance/disable
```

## Rollback Testing Strategy

### Pre-Production Testing

1. **Migration Testing Environment**:
   - Identical to production schema
   - Test data that mirrors production patterns
   - Automated rollback testing pipeline

2. **Rollback Scenarios**:
   - Immediate rollback (within 5 minutes)
   - Delayed rollback (after hours/days)
   - Partial rollback (specific tables only)
   - Emergency rollback (system failure)

3. **Validation Procedures**:
   - Data integrity verification
   - Performance impact assessment
   - Application functionality testing
   - Compliance requirement verification

### Rollback Automation

```python
# rollback_automation.py - Automated rollback testing

class RollbackTester:
    def test_migration_rollback(self, migration_id):
        # 1. Apply migration
        self.apply_migration(migration_id)
        
        # 2. Insert test data
        test_data = self.create_test_data()
        
        # 3. Execute rollback
        rollback_result = self.execute_rollback(migration_id)
        
        # 4. Verify data integrity
        integrity_check = self.verify_integrity()
        
        # 5. Test application functionality
        functionality_check = self.test_app_functionality()
        
        return {
            'rollback_successful': rollback_result.success,
            'data_integrity': integrity_check.passed,
            'functionality': functionality_check.passed,
            'duration': rollback_result.duration
        }
```

## Monitoring and Alerting

### Rollback Metrics

1. **Timing Metrics**:
   - Rollback execution time
   - Service recovery time
   - Data verification time

2. **Data Metrics**:
   - Records affected
   - Data consistency checks
   - Audit chain integrity

3. **Business Metrics**:
   - Service availability
   - User impact assessment
   - Financial transaction integrity

### Alert Conditions

```yaml
# rollback_alerts.yml
alerts:
  rollback_initiated:
    condition: "rollback_started"
    severity: "warning"
    notification: "slack_ops_channel"
    
  rollback_failed:
    condition: "rollback_error"
    severity: "critical"
    notification: ["slack_ops_channel", "email_oncall"]
    
  data_integrity_warning:
    condition: "integrity_check_failed"
    severity: "critical"
    notification: ["slack_ops_channel", "email_dba"]
    
  audit_chain_broken:
    condition: "audit_chain_invalid"
    severity: "critical"
    notification: ["slack_ops_channel", "email_compliance"]
```

## Compliance Considerations

### Turkish Regulatory Requirements

1. **Audit Trail Preservation**:
   - Complete audit history must be maintained
   - Rollbacks must be documented in audit logs
   - Regulatory authorities must be notified of significant rollbacks

2. **Financial Data Protection**:
   - All financial calculations must remain accurate
   - Currency conversion rates must be preserved
   - Tax calculations (KDV) must remain valid

3. **Data Protection (KVKV)**:
   - Personal data must remain protected during rollbacks
   - Data retention policies must be respected
   - User consent records must be preserved

### Documentation Requirements

1. **Rollback Documentation**:
   - Reason for rollback
   - Steps executed
   - Data affected
   - Recovery time
   - Lessons learned

2. **Compliance Reporting**:
   - Regulatory notification (if required)
   - Impact assessment report
   - Corrective action plan
   - Prevention measures

This comprehensive rollback strategy ensures that the system can recover from any migration issues while maintaining data integrity, business continuity, and regulatory compliance.