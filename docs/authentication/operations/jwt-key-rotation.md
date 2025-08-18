# JWT Key Rotation Operational Playbook
## Ultra-Enterprise Banking Grade Key Management

**Version**: 1.0.0  
**Classification**: CONFIDENTIAL - OPERATIONS CRITICAL  
**Last Updated**: 2025-08-18  
**Compliance**: Turkish Banking Regulation, KVKV, ISO 27001  

## Overview

This playbook provides step-by-step procedures for rotating JWT signing keys in the ultra-enterprise authentication system. Key rotation is critical for maintaining security and compliance with banking-level standards.

## Key Rotation Schedule

### Regular Rotation
- **Frequency**: Every 90 days
- **Window**: Maintenance window (02:00-04:00 TR time)
- **Notification**: 48 hours advance notice
- **Rollback**: 4-hour rollback window

### Emergency Rotation
- **Trigger**: Suspected key compromise
- **Frequency**: Immediate
- **Window**: Any time (24/7)
- **Notification**: Immediate security alert
- **Rollback**: 30-minute rollback window

## JWT Key Architecture

### Key Management System

```
┌─────────────────────────────────────────┐
│           Key Management Store          │
├─────────────────────────────────────────┤
│ Current Keys (Active)                   │
│ • Primary Signing Key (kid: current)   │
│ • Public Key for Verification          │
├─────────────────────────────────────────┤
│ Previous Keys (Grace Period)           │
│ • Old Signing Key (kid: previous)      │ 
│ • Public Key for Verification          │
├─────────────────────────────────────────┤
│ Future Keys (Prepared)                 │
│ • New Signing Key (kid: next)          │
│ • Public Key for Verification          │
└─────────────────────────────────────────┘
```

### Key Identifier (kid) Strategy

- **Format**: `{timestamp}_{version}_{environment}`
- **Example**: `20250118_v1_prod`
- **Rotation**: New kid generated for each rotation
- **Tracking**: All historical kids maintained in JWKS

## Pre-Rotation Checklist

### 24 Hours Before Rotation

**✅ Preparation Phase**
- [ ] Schedule maintenance window
- [ ] Notify stakeholders (Security, Operations, Development)
- [ ] Verify backup systems operational
- [ ] Check monitoring systems status
- [ ] Prepare rollback procedures

**✅ Key Generation**
- [ ] Generate new RSA key pair (4096-bit)
- [ ] Validate key strength and format
- [ ] Store private key in secure key management system
- [ ] Generate new kid identifier
- [ ] Test key signing/verification

**✅ Environment Verification**
- [ ] Verify all application instances accessible
- [ ] Check database connectivity
- [ ] Validate Redis cluster health
- [ ] Test external service dependencies
- [ ] Confirm load balancer configuration

### 1 Hour Before Rotation

**✅ Final Checks**
- [ ] Confirm no active deployments
- [ ] Verify system stability metrics
- [ ] Check error rates and performance
- [ ] Ensure on-call team availability
- [ ] Validate communication channels

## Regular Key Rotation Procedure

### Phase 1: Key Preparation (15 minutes)

#### Step 1.1: Generate New Key Pair
```bash
#!/bin/bash
# Generate new JWT signing key pair

TIMESTAMP=$(date +%Y%m%d_%H%M)
KID="jwt_${TIMESTAMP}_v1_prod"
KEY_DIR="/secure/keys/jwt"

# Generate RSA 4096-bit private key
openssl genpkey -algorithm RSA -out "${KEY_DIR}/${KID}_private.pem" \
    -pkcs8 -aes256 -pass pass:"${JWT_KEY_PASSPHRASE}" \
    -pkeyopt rsa_keygen_bits:4096

# Extract public key
openssl pkey -in "${KEY_DIR}/${KID}_private.pem" \
    -passin pass:"${JWT_KEY_PASSPHRASE}" \
    -pubout -out "${KEY_DIR}/${KID}_public.pem"

# Set secure permissions
chmod 600 "${KEY_DIR}/${KID}_private.pem"
chmod 644 "${KEY_DIR}/${KID}_public.pem"
chown jwt-service:jwt-service "${KEY_DIR}/${KID}"*

echo "New JWT key pair generated: ${KID}"
```

#### Step 1.2: Validate Key Pair
```bash
#!/bin/bash
# Validate new JWT key pair

KID="$1"
KEY_DIR="/secure/keys/jwt"

# Test signing with private key
echo "Testing JWT signing capability..."
TEST_TOKEN=$(python3 -c "
import jwt
import datetime

private_key = open('${KEY_DIR}/${KID}_private.pem', 'rb').read()
payload = {'test': True, 'exp': datetime.datetime.utcnow() + datetime.timedelta(minutes=5)}
token = jwt.encode(payload, private_key, algorithm='RS256', headers={'kid': '${KID}'})
print(token)
")

# Test verification with public key
echo "Testing JWT verification capability..."
python3 -c "
import jwt

public_key = open('${KEY_DIR}/${KID}_public.pem', 'rb').read()
token = '${TEST_TOKEN}'
decoded = jwt.decode(token, public_key, algorithms=['RS256'])
print('Key validation successful:', decoded)
"

echo "Key pair validation completed successfully"
```

#### Step 1.3: Update Key Management Database
```sql
-- Insert new key into key management table
INSERT INTO jwt_signing_keys (
    kid,
    private_key_path,
    public_key_pem,
    algorithm,
    key_size,
    status,
    created_at,
    valid_from,
    valid_until
) VALUES (
    '{NEW_KID}',
    '/secure/keys/jwt/{NEW_KID}_private.pem',
    '{PUBLIC_KEY_PEM}',
    'RS256',
    4096,
    'prepared',
    NOW(),
    NOW() + INTERVAL '30 minutes',  -- Grace period before activation
    NOW() + INTERVAL '120 days'     -- 4 months validity
);
```

### Phase 2: Key Deployment (20 minutes)

#### Step 2.1: Update Application Configuration
```python
# Update JWT service configuration
async def update_jwt_key_config(new_kid: str):
    """Update JWT key configuration in all application instances."""
    
    config_updates = {
        'JWT_SIGNING_KEY_ID': new_kid,
        'JWT_VERIFICATION_KEYS': get_active_verification_keys(),
        'JWT_KEY_ROTATION_TIMESTAMP': datetime.utcnow().isoformat()
    }
    
    # Update configuration in database
    await update_system_config(config_updates)
    
    # Trigger configuration reload across all instances
    await broadcast_config_update('jwt_key_rotation', config_updates)
    
    logger.info("JWT key configuration updated", extra={
        'operation': 'jwt_key_rotation',
        'new_kid': new_kid,
        'phase': 'configuration_update'
    })
```

#### Step 2.2: Rolling Instance Update
```bash
#!/bin/bash
# Rolling update of application instances

INSTANCES=(
    "api-instance-1"
    "api-instance-2" 
    "api-instance-3"
    "worker-instance-1"
    "worker-instance-2"
)

for instance in "${INSTANCES[@]}"; do
    echo "Updating instance: ${instance}"
    
    # Trigger graceful config reload
    kubectl exec -n freecad-cnc "${instance}" -- \
        /app/scripts/reload-jwt-config.sh
    
    # Wait for instance to report ready
    kubectl wait --for=condition=Ready pod/"${instance}" -n freecad-cnc --timeout=60s
    
    # Verify JWT functionality
    curl -f "http://${instance}:8000/health/jwt" || {
        echo "JWT health check failed for ${instance}"
        exit 1
    }
    
    echo "Instance ${instance} updated successfully"
    sleep 10  # Brief pause between instances
done

echo "All instances updated successfully"
```

#### Step 2.3: Update JWKS Endpoint
```python
def update_jwks_endpoint():
    """Update JSON Web Key Set endpoint with new keys."""
    
    # Get all valid verification keys
    active_keys = get_active_jwt_keys()
    
    jwks = {
        "keys": []
    }
    
    for key in active_keys:
        # Convert PEM to JWK format
        jwk = convert_pem_to_jwk(key.public_key_pem)
        jwk.update({
            "kid": key.kid,
            "alg": key.algorithm,
            "use": "sig",
            "key_ops": ["verify"]
        })
        jwks["keys"].append(jwk)
    
    # Update JWKS in Redis cache
    await redis_client.set(
        "jwks:current", 
        json.dumps(jwks),
        ex=3600  # 1 hour cache
    )
    
    # Update JWKS in database
    await update_jwks_cache(jwks)
    
    logger.info("JWKS endpoint updated", extra={
        'operation': 'jwt_key_rotation',
        'active_keys': len(active_keys),
        'phase': 'jwks_update'
    })
```

### Phase 3: Key Activation (10 minutes)

#### Step 3.1: Activate New Signing Key
```sql
-- Transaction to safely activate new key
BEGIN;

-- Mark current key as previous
UPDATE jwt_signing_keys 
SET status = 'previous',
    deactivated_at = NOW()
WHERE status = 'current';

-- Activate new key
UPDATE jwt_signing_keys
SET status = 'current',
    activated_at = NOW()
WHERE kid = '{NEW_KID}' AND status = 'prepared';

-- Verify exactly one current key exists
SELECT COUNT(*) as current_key_count 
FROM jwt_signing_keys 
WHERE status = 'current';
-- Must return exactly 1

COMMIT;
```

#### Step 3.2: Verify New Token Generation
```bash
#!/bin/bash
# Test new JWT token generation and verification

echo "Testing new JWT token generation..."

# Generate test token with new key
curl -X POST "http://localhost:8000/api/v1/auth/test-jwt" \
    -H "Content-Type: application/json" \
    -d '{"test": true}' | jq .

# Verify token can be validated
TEST_RESPONSE=$(curl -s -X GET "http://localhost:8000/api/v1/auth/verify-jwt")
echo "JWT verification test: $TEST_RESPONSE"

# Check JWKS endpoint includes new key
curl -s "http://localhost:8000/.well-known/jwks.json" | \
    jq '.keys[] | select(.kid == "'${NEW_KID}'")'

echo "JWT activation verification completed"
```

### Phase 4: Monitoring and Validation (15 minutes)

#### Step 4.1: Monitor Token Validation Metrics
```python
def monitor_jwt_validation_metrics():
    """Monitor JWT validation success rates after rotation."""
    
    metrics = {
        'token_generation_success_rate': get_metric('jwt_generation_success'),
        'token_validation_success_rate': get_metric('jwt_validation_success'),
        'token_validation_errors': get_metric('jwt_validation_errors'),
        'active_sessions_count': get_metric('active_sessions'),
        'new_key_usage_percentage': get_metric(f'jwt_key_usage_{NEW_KID}')
    }
    
    # Check for acceptable thresholds
    if metrics['token_validation_success_rate'] < 0.95:
        alert('JWT validation success rate below 95% after key rotation')
    
    if metrics['token_validation_errors'] > 100:
        alert('High JWT validation error count after key rotation')
    
    logger.info("JWT rotation metrics", extra={
        'operation': 'jwt_key_rotation',
        'phase': 'monitoring',
        'metrics': metrics
    })
    
    return metrics
```

#### Step 4.2: Validate User Sessions
```sql
-- Check for session validation issues
SELECT 
    COUNT(*) as total_sessions,
    COUNT(CASE WHEN last_validated_at > NOW() - INTERVAL '10 minutes' THEN 1 END) as recent_validations,
    COUNT(CASE WHEN validation_errors > 0 THEN 1 END) as sessions_with_errors
FROM user_sessions 
WHERE status = 'active';

-- Check for authentication errors in recent logs
SELECT 
    COUNT(*) as auth_errors,
    error_code,
    COUNT(*) as frequency
FROM audit_logs 
WHERE operation = 'jwt_validation_error'
    AND created_at > NOW() - INTERVAL '15 minutes'
GROUP BY error_code
ORDER BY frequency DESC;
```

### Phase 5: Cleanup and Documentation (15 minutes)

#### Step 5.1: Schedule Old Key Cleanup
```sql
-- Schedule old keys for cleanup (keep for 30 days)
UPDATE jwt_signing_keys
SET 
    status = 'deprecated',
    cleanup_scheduled_at = NOW() + INTERVAL '30 days'
WHERE status = 'previous' 
    AND deactivated_at < NOW() - INTERVAL '7 days';
```

#### Step 5.2: Update Documentation
```python
def document_key_rotation(rotation_details):
    """Document completed key rotation."""
    
    rotation_record = {
        'rotation_id': generate_rotation_id(),
        'timestamp': datetime.utcnow(),
        'old_kid': rotation_details['old_kid'],
        'new_kid': rotation_details['new_kid'],
        'rotation_type': 'scheduled',
        'duration_minutes': rotation_details['duration'],
        'success': True,
        'notes': 'Regular 90-day key rotation completed successfully',
        'performed_by': get_operator_info(),
        'validation_metrics': rotation_details['metrics']
    }
    
    # Store rotation record
    await store_rotation_record(rotation_record)
    
    # Update key rotation schedule
    await schedule_next_rotation(days=90)
    
    # Send completion notifications
    await notify_rotation_completion(rotation_record)
```

## Emergency Key Rotation Procedure

### Immediate Response (Within 30 minutes)

#### Emergency Activation Checklist

**⚠️ CRITICAL - Execute immediately upon key compromise detection**

1. **Incident Declaration**
   ```bash
   # Declare security incident
   ./scripts/declare-security-incident.sh jwt-key-compromise
   ```

2. **Immediate Key Deactivation**
   ```sql
   -- Immediately deactivate compromised key
   UPDATE jwt_signing_keys 
   SET status = 'compromised', 
       compromised_at = NOW(),
       compromised_reason = 'Security incident - immediate rotation required'
   WHERE status = 'current';
   ```

3. **Emergency Key Activation**
   ```bash
   # Use pre-generated emergency key
   ./scripts/activate-emergency-jwt-key.sh
   ```

4. **Revoke All Active Sessions**
   ```sql
   -- Revoke all active sessions signed with compromised key
   UPDATE user_sessions 
   SET status = 'revoked',
       revoked_at = NOW(),
       revoked_reason = 'Key compromise security incident'
   WHERE status = 'active';
   ```

5. **Force User Re-authentication**
   ```python
   # Force all users to re-authenticate
   await force_global_reauthentication(
       reason="Security maintenance - please log in again"
   )
   ```

### Post-Emergency Procedures (Within 4 hours)

1. **Security Investigation**
   - Analyze compromise source
   - Review access logs
   - Identify affected tokens
   - Document timeline

2. **System Validation**
   - Verify new key functionality
   - Check authentication flows
   - Validate session management
   - Test API endpoints

3. **Compliance Reporting**
   - Notify regulatory authorities (Turkish Banking)
   - Document KVKV data protection measures
   - Prepare incident report
   - Update security procedures

## Rollback Procedures

### Rollback Decision Matrix

| Scenario | Rollback Trigger | Action |
|----------|------------------|---------|
| High error rate (>5%) | Within 30 minutes | Immediate rollback |
| Authentication failures | Within 15 minutes | Immediate rollback |
| System instability | Within 45 minutes | Investigate then rollback |
| User complaints | Within 60 minutes | Monitor then decide |

### Rollback Execution

#### Step 1: Immediate Rollback
```sql
-- Emergency rollback to previous key
BEGIN;

-- Deactivate problematic key
UPDATE jwt_signing_keys 
SET status = 'failed',
    rollback_at = NOW()
WHERE status = 'current';

-- Reactivate previous key
UPDATE jwt_signing_keys
SET status = 'current',
    reactivated_at = NOW()
WHERE status = 'previous'
ORDER BY deactivated_at DESC
LIMIT 1;

COMMIT;
```

#### Step 2: Configuration Rollback
```bash
# Rollback application configuration
kubectl rollout undo deployment/freecad-api -n freecad-cnc

# Verify rollback success
kubectl rollout status deployment/freecad-api -n freecad-cnc
```

#### Step 3: Validation
```python
def validate_rollback():
    """Validate successful rollback to previous key."""
    
    # Test token generation
    test_token = generate_test_jwt_token()
    
    # Test token validation
    validation_result = validate_jwt_token(test_token)
    
    # Check metrics
    success_rate = get_jwt_validation_success_rate(minutes=5)
    
    if success_rate > 0.95 and validation_result.valid:
        logger.info("Rollback validation successful")
        return True
    else:
        logger.error("Rollback validation failed")
        return False
```

## Monitoring and Alerting

### Key Rotation Metrics

#### Pre-Rotation Metrics
- System stability (error rate < 1%)
- Authentication success rate (> 99%)
- Active session count
- Database performance metrics

#### During Rotation Metrics  
- Token generation success rate
- Token validation success rate
- Authentication error count
- Session validation errors

#### Post-Rotation Metrics
- User experience metrics
- Authentication latency
- Session persistence rate
- Security event frequency

### Automated Monitoring

```python
class JWTRotationMonitor:
    """Automated monitoring for JWT key rotations."""
    
    def __init__(self):
        self.alert_thresholds = {
            'validation_success_rate': 0.95,
            'generation_success_rate': 0.98,
            'error_rate': 0.05,
            'latency_ms': 100
        }
    
    async def monitor_rotation_health(self, duration_minutes: int = 60):
        """Monitor JWT system health during rotation."""
        
        metrics = await self.collect_jwt_metrics(duration_minutes)
        
        alerts = []
        for metric, threshold in self.alert_thresholds.items():
            if metrics.get(metric, 0) < threshold:
                alerts.append(f"JWT {metric} below threshold: {metrics[metric]}")
        
        if alerts:
            await self.send_rotation_alerts(alerts)
        
        return metrics
    
    async def send_rotation_alerts(self, alerts: List[str]):
        """Send alerts for JWT rotation issues."""
        
        alert_message = {
            'severity': 'HIGH',
            'service': 'JWT Key Rotation',
            'alerts': alerts,
            'action_required': 'Review JWT rotation status immediately',
            'playbook': 'docs/authentication/operations/jwt-key-rotation.md'
        }
        
        # Send to operations team
        await send_slack_alert('#security-ops', alert_message)
        await send_email_alert('security-ops@freecad-cnc.com.tr', alert_message)
```

### Dashboards

Create monitoring dashboards with:

1. **JWT Key Status Dashboard**
   - Active key information
   - Key rotation schedule
   - Historical rotation timeline
   - Key usage metrics

2. **Authentication Health Dashboard**
   - Token generation/validation rates
   - Authentication success metrics
   - Error rate trends
   - Session validation status

3. **Security Incident Dashboard**
   - Key compromise alerts
   - Emergency rotation triggers
   - Incident response timeline
   - Recovery status

## Compliance and Audit

### Regulatory Requirements

#### Turkish Banking Regulation
- Key rotation every 90 days maximum
- Incident reporting within 4 hours
- Audit trail maintenance for 7 years
- Multi-person authorization for key operations

#### KVKV Compliance
- Data protection during key rotation
- User notification of security maintenance
- Privacy impact assessment
- Data processing audit logs

### Audit Trail

All key rotation activities must generate comprehensive audit records:

```python
def create_key_rotation_audit_record(operation_details):
    """Create comprehensive audit record for key rotation."""
    
    audit_record = {
        'event_type': 'JWT_KEY_ROTATION',
        'timestamp': datetime.utcnow(),
        'operation': operation_details['operation'],
        'operator': operation_details['operator'],
        'old_key_id': operation_details['old_kid'],
        'new_key_id': operation_details['new_kid'],
        'rotation_type': operation_details['type'],  # scheduled/emergency
        'duration_seconds': operation_details['duration'],
        'success': operation_details['success'],
        'affected_sessions': operation_details['session_count'],
        'system_impact': operation_details['impact_assessment'],
        'compliance_notes': operation_details['compliance'],
        'approval_chain': operation_details['approvals']
    }
    
    # Store in immutable audit log
    await store_immutable_audit_record(audit_record)
    
    # Send to external audit system
    await send_to_external_audit_system(audit_record)
```

## Contact Information

### Emergency Escalation

**Level 1 - Operations Team**
- Slack: #ops-security
- Phone: +90-XXX-XXX-1111
- Response Time: 15 minutes

**Level 2 - Security Team**
- Email: security@freecad-cnc.com.tr
- Phone: +90-XXX-XXX-2222
- Response Time: 30 minutes

**Level 3 - Executive**
- CISO: ciso@freecad-cnc.com.tr
- Phone: +90-XXX-XXX-3333
- Response Time: 1 hour

### Key Personnel

| Role | Contact | Backup |
|------|---------|---------|
| JWT Key Manager | ops-lead@domain.com | security-lead@domain.com |
| Database Administrator | dba@domain.com | dba-backup@domain.com |
| Security Officer | security@domain.com | ciso@domain.com |
| Compliance Officer | compliance@domain.com | legal@domain.com |

---

## Appendix

### Key Generation Scripts

See `/scripts/jwt-key-management/` directory for:
- `generate-jwt-keys.sh` - New key generation
- `validate-jwt-keys.sh` - Key validation
- `activate-jwt-keys.sh` - Key activation
- `emergency-rotation.sh` - Emergency procedures
- `cleanup-old-keys.sh` - Key cleanup

### Testing Procedures

See `/tests/jwt-key-rotation/` directory for:
- Unit tests for key rotation logic
- Integration tests for full rotation flow
- Load tests for rotation impact
- Security tests for key validation

---

**🔐 GÜVENLİK UYARISI**: Bu dokuman hassas güvenlik bilgileri içermektedir. Yetkisiz erişim, kullanım veya paylaşım yasaktır.

**📊 PERFORMANS**: JWT key rotation işlemi ortalama 60 dakikada tamamlanır ve kullanıcı deneyimini minimal düzeyde etkiler.

**🇹🇷 KVKV UYUMLULUĞU**: Tüm key rotation işlemleri Türkiye veri koruma mevzuatına uygun olarak gerçekleştirilir ve loglanır.