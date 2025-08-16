# Secret Yönetimi ve Güvenlik Stratejisi

## İçindekiler
1. [Genel Bakış](#genel-bakış)
2. [Güvenlik İlkeleri](#güvenlik-ilkeleri)
3. [Ortam Konfigürasyonları](#ortam-konfigürasyonları)
4. [Secret Management Araçları](#secret-management-araçları)
5. [Kubernetes Secrets](#kubernetes-secrets)
6. [En İyi Güvenlik Uygulamaları](#en-iyi-güvenlik-uygulamaları)
7. [Compliance ve Denetim](#compliance-ve-denetim)
8. [Incident Response](#incident-response)

## Genel Bakış

CNC AI Suite platformu için güvenli secret yönetimi stratejisi, defense-in-depth yaklaşımı ile tasarlanmıştır. Tüm hassas bilgiler external secret management sistemlerinde saklanır ve hiçbir zaman kaynak koduna dahil edilmez.

### Kritik Secret Kategorileri

1. **Veritabanı Credentials**: PostgreSQL kullanıcı adı, şifre, connection string
2. **API Keys**: OpenAI, Azure OpenAI, Google OAuth anahtarları
3. **Storage Credentials**: S3/MinIO access keys, bucket credentials
4. **Monitoring Tokens**: Sentry DSN, OpenTelemetry endpoints
5. **Encryption Keys**: JWT secret, data encryption keys
6. **Service Accounts**: Kubernetes service account tokens, cloud provider credentials

## Güvenlik İlkeleri

### 1. Zero Trust Principle
- Hiçbir secret kaynak kodunda saklanmaz
- Tüm secret'lar external vault'larda encrypt edilir
- Runtime'da environment variable'lar ile inject edilir
- Regular rotation ve audit yapılır

### 2. Least Privilege Access
- Her service sadece ihtiyaç duyduğu secret'lara erişebilir
- Role-based access control (RBAC) uygulanır
- Temporary access tokens kullanılır
- Service account permissions minimize edilir

### 3. Defense in Depth
- Multiple encryption layers (transit + rest)
- Network segmentation ve firewall rules
- API rate limiting ve throttling
- Comprehensive monitoring ve alerting

### 4. Compliance Requirements
- **KVKK (Türkiye)**: Kişisel veri koruma uyumluluğu
- **GDPR**: Avrupa veri koruma standardları
- **ISO 27001**: Bilgi güvenliği yönetim sistemi
- **SOC 2 Type 2**: Güvenlik ve availability controls

## Ortam Konfigürasyonları

### Development Environment (.env.example)
```bash
# Sadece geliştirme için mock değerler
SECRET_KEY=dev-secret-key-change-in-production-minimum-32-chars
OPENAI_API_KEY=sk-dev-mock-key-for-testing-only
POSTGRES_PASSWORD=dev_password_changeme
```

**Güvenlik Özellikleri:**
- Tüm secret'lar mock değerler
- Production API'larına bağlantı yok
- Local development isolation
- Güçlü password policy

### Test Environment (.env.test)
```bash
# Test için izole edilmiş ayarlar
SECRET_KEY=test-secret-key-for-testing-only-32-chars-minimum
DATABASE_URL=postgresql+psycopg2://test_user:test_password@localhost:5433/freecad_test
MOCK_EXTERNAL_SERVICES=true
```

**Güvenlik Özellikleri:**
- Ayrı test database ve Redis
- Mock external services
- Test-specific credentials
- Automatic cleanup

### Production Environment (.env.prod.example)
```bash
# Template - gerçek değerler external vault'tan gelir
SECRET_KEY=${SECRET_JWT_KEY}
OPENAI_API_KEY=${SECRET_OPENAI_API_KEY}
DATABASE_URL=${SECRET_DATABASE_URL}
```

**Güvenlik Özellikleri:**
- Tüm secret'lar placeholder
- External secret injection
- Strong encryption requirements
- Audit trail

## Secret Management Araçları

### 1. Doppler (Önerilen)

**Kurulum:**
```bash
# Doppler CLI kurulumu
curl -Ls https://cli.doppler.com/install.sh | sh

# Project setup
doppler setup
doppler secrets set SECRET_KEY="your-production-secret"
```

**Production deployment:**
```bash
# Secret'ları inject ederek çalıştırma
doppler run -- docker-compose up
doppler run -- ./start.sh
```

**Özellikler:**
- ✅ End-to-end encryption
- ✅ Role-based access control
- ✅ Audit logging ve versioning
- ✅ Multi-environment support
- ✅ Team collaboration features

### 2. HashiCorp Vault

**Vault integration:**
```bash
# Secret yazma
vault kv put secret/freecad/prod \
  secret_key="..." \
  openai_api_key="..." \
  database_url="..."

# Secret okuma
export SECRET_KEY=$(vault kv get -field=secret_key secret/freecad/prod)
```

**Advanced features:**
```bash
# Dynamic secrets
vault write database/config/postgres \
  plugin_name=postgresql-database-plugin \
  connection_url="postgresql://{{username}}:{{password}}@postgres:5432/freecad" \
  allowed_roles="freecad-role"

# Temporary credentials (1 hour TTL)
vault read database/creds/freecad-role
```

### 3. Azure Key Vault

**ARM Template integration:**
```json
{
  "type": "Microsoft.KeyVault/vaults",
  "apiVersion": "2021-11-01-preview",
  "name": "[variables('keyVaultName')]",
  "properties": {
    "tenantId": "[subscription().tenantId]",
    "sku": {
      "family": "A",
      "name": "premium"
    },
    "accessPolicies": [
      {
        "tenantId": "[subscription().tenantId]",
        "objectId": "[reference(resourceId('Microsoft.ManagedIdentity/userAssignedIdentities', variables('identityName'))).principalId]",
        "permissions": {
          "secrets": ["get", "list"]
        }
      }
    ]
  }
}
```

**Application integration:**
```csharp
// Key Vault reference in App Service
@Microsoft.KeyVault(SecretUri=https://vault.vault.azure.net/secrets/secret-key/)
```

## Kubernetes Secrets

### Base64 Encoding (Güvenli Değil!)
```bash
# ASLA bunu kullanmayın - sadece örnek
echo -n "my-secret" | base64
```

### External Secrets Operator (Önerilen)
```yaml
apiVersion: external-secrets.io/v1beta1
kind: SecretStore
metadata:
  name: vault-backend
spec:
  provider:
    vault:
      server: "https://vault.company.com"
      path: "secret"
      version: "v2"
      auth:
        kubernetes:
          mountPath: "kubernetes"
          role: "freecad-api"
---
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: freecad-secrets
spec:
  refreshInterval: 15s
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: freecad-api-secrets
    creationPolicy: Owner
  data:
  - secretKey: secret-key
    remoteRef:
      key: freecad/prod
      property: secret_key
  - secretKey: openai-api-key
    remoteRef:
      key: freecad/prod
      property: openai_api_key
```

### Sealed Secrets
```bash
# Sealed secret oluşturma
echo -n "my-secret" | kubectl create secret generic my-secret --dry-run=client --from-file=secret=/dev/stdin -o yaml | kubeseal -o yaml > sealed-secret.yaml

# Deploy
kubectl apply -f sealed-secret.yaml
```

### CSI Secret Store Driver
```yaml
apiVersion: v1
kind: SecretProviderClass
metadata:
  name: freecad-secrets
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "true"
    userAssignedIdentityClientID: "client-id"
    keyvaultName: "freecad-vault"
    objects: |
      array:
        - |
          objectName: secret-key
          objectType: secret
        - |
          objectName: openai-api-key
          objectType: secret
```

## En İyi Güvenlik Uygulamaları

### 1. Secret Rotation
```bash
# Automated rotation script
#!/bin/bash
set -euo pipefail

# JWT secret rotation (monthly)
if [[ $(date +%d) == "01" ]]; then
  NEW_SECRET=$(openssl rand -base64 32)
  doppler secrets set SECRET_KEY="$NEW_SECRET"
  kubectl rollout restart deployment/freecad-api
fi

# Database password rotation (quarterly)
if [[ $(date +%m%d) == "0101" ]] || [[ $(date +%m%d) == "0401" ]] || [[ $(date +%m%d) == "0701" ]] || [[ $(date +%m%d) == "1001" ]]; then
  # Koordinated rotation with zero downtime
  ./rotate-db-credentials.sh
fi
```

### 2. Access Control
```yaml
# RBAC for secret access
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: secret-reader
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["freecad-api-secrets"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: freecad-api-secret-binding
subjects:
- kind: ServiceAccount
  name: freecad-api
roleRef:
  kind: Role
  name: secret-reader
  apiGroup: rbac.authorization.k8s.io
```

### 3. Network Security
```yaml
# Network policies
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: freecad-api-netpol
spec:
  podSelector:
    matchLabels:
      app: freecad-api
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: freecad-web
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
```

### 4. Monitoring ve Alerting
```yaml
# Prometheus alert rules
groups:
- name: security
  rules:
  - alert: SecretAccessFailure
    expr: increase(kubernetes_secret_access_failures_total[5m]) > 5
    for: 2m
    labels:
      severity: critical
    annotations:
      summary: "Unusual secret access failures detected"
      description: "{{ $value }} secret access failures in the last 5 minutes"

  - alert: UnauthorizedSecretAccess
    expr: rate(kubernetes_audit_total{verb="get",objectRef_resource="secrets",user_username!~"system:.*"}[5m]) > 0.1
    for: 1m
    labels:
      severity: warning
    annotations:
      summary: "Unauthorized secret access attempt"
      description: "User {{ $labels.user_username }} accessed secret {{ $labels.objectRef_name }}"
```

## Compliance ve Denetim

### KVKK (Türk Kişisel Verileri Koruma Kanunu) Uyumluluğu

**Gereksinimler:**
- Kişisel verilerin şifrelenmesi
- Erişim loglarının tutulması  
- Veri işleme izinlerinin kayıt altına alınması
- Veri sahibi hakları (erişim, düzeltme, silme)

**Uygulama:**
```python
# PII encryption middleware
from cryptography.fernet import Fernet

class PIIEncryption:
    def __init__(self, key: str):
        self.cipher = Fernet(key.encode())
    
    def encrypt_pii(self, data: str) -> str:
        """KVKK uyumlu PII şifreleme"""
        return self.cipher.encrypt(data.encode()).decode()
    
    def decrypt_pii(self, encrypted_data: str) -> str:
        """KVKK uyumlu PII çözümleme"""
        return self.cipher.decrypt(encrypted_data.encode()).decode()

# Audit logging
import structlog
logger = structlog.get_logger()

def log_pii_access(user_id: str, pii_type: str, action: str):
    """KVKK uyumlu PII erişim logu"""
    logger.info(
        "pii_access",
        user_id=user_id,
        pii_type=pii_type,
        action=action,
        timestamp=datetime.utcnow().isoformat(),
        compliance="KVKK"
    )
```

### GDPR Uyumluluğu

**Data Subject Rights:**
```python
class GDPRCompliance:
    
    def right_to_access(self, user_id: str) -> Dict:
        """Veri sahibinin kişisel verilerine erişim hakkı"""
        user_data = self.get_user_data(user_id)
        processing_log = self.get_processing_log(user_id)
        return {
            "personal_data": user_data,
            "processing_activities": processing_log,
            "retention_period": "7 years",
            "third_party_sharing": self.get_third_party_sharing(user_id)
        }
    
    def right_to_rectification(self, user_id: str, corrections: Dict):
        """Veri sahibinin verilerini düzeltme hakkı"""
        self.update_user_data(user_id, corrections)
        self.log_rectification(user_id, corrections)
    
    def right_to_erasure(self, user_id: str):
        """Unutulma hakkı (Right to be forgotten)"""
        self.anonymize_user_data(user_id)
        self.log_erasure(user_id)
```

### Audit Trail Implementation
```python
from sqlalchemy import create_engine, Column, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()

class AuditLog(Base):
    __tablename__ = "audit_logs"
    
    id = Column(String, primary_key=True)
    timestamp = Column(DateTime, nullable=False)
    user_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    resource = Column(String, nullable=False)
    ip_address = Column(String)
    user_agent = Column(String)
    success = Column(Boolean, nullable=False)
    details = Column(Text)
    compliance_flags = Column(String)  # KVKK, GDPR, SOX

def audit_secret_access(user_id: str, secret_name: str, success: bool):
    """Secret erişimi audit logu"""
    audit = AuditLog(
        id=str(uuid.uuid4()),
        timestamp=datetime.utcnow(),
        user_id=user_id,
        action="SECRET_ACCESS",
        resource=secret_name,
        success=success,
        compliance_flags="KVKK,GDPR,SOC2"
    )
    db.session.add(audit)
    db.session.commit()
```

## Incident Response

### 1. Secret Compromise Detection
```bash
#!/bin/bash
# Secret compromise detection script

check_secret_compromise() {
    local secret_name=$1
    
    # Check for unusual access patterns
    kubectl logs deployment/freecad-api | grep "SECRET_ACCESS_FAILURE" | tail -100
    
    # Check audit logs
    curl -X GET "https://api.company.com/audit/secrets/$secret_name/access" \
         -H "Authorization: Bearer $AUDIT_TOKEN"
    
    # Verify secret integrity
    current_hash=$(doppler secrets get $secret_name --plain | sha256sum)
    last_known_hash=$(redis-cli get "secret:$secret_name:hash")
    
    if [[ "$current_hash" != "$last_known_hash" ]]; then
        echo "ALERT: Secret $secret_name may be compromised!"
        return 1
    fi
}

# Automated monitoring
while true; do
    for secret in SECRET_KEY OPENAI_API_KEY DATABASE_URL; do
        check_secret_compromise $secret
    done
    sleep 300  # Check every 5 minutes
done
```

### 2. Incident Response Playbook

**Phase 1: Detection & Assessment (0-15 minutes)**
1. Automated alerting system detection
2. Security team notification
3. Initial impact assessment
4. Evidence preservation

**Phase 2: Containment (15-30 minutes)**
1. Revoke compromised secrets immediately
2. Rotate all related credentials
3. Isolate affected systems
4. Block suspicious IP addresses

**Phase 3: Eradication (30-60 minutes)**
1. Identify root cause
2. Remove any backdoors or persistent access
3. Update security controls
4. Patch vulnerabilities

**Phase 4: Recovery (1-4 hours)**
1. Generate new secure secrets
2. Update all applications with new credentials
3. Restore service functionality
4. Monitor for anomalies

**Phase 5: Lessons Learned (24-48 hours)**
1. Document incident timeline
2. Update security procedures
3. Enhance monitoring and detection
4. Train team on new procedures

### 3. Emergency Secret Rotation
```bash
#!/bin/bash
# Emergency secret rotation script

emergency_rotate() {
    local secret_name=$1
    echo "EMERGENCY: Rotating $secret_name"
    
    # Generate new secure secret
    case $secret_name in
        "SECRET_KEY")
            new_value=$(openssl rand -base64 32)
            ;;
        "OPENAI_API_KEY")
            echo "Manual OpenAI key rotation required!"
            exit 1
            ;;
        "DATABASE_URL")
            echo "Database credential rotation requires coordination!"
            exit 1
            ;;
        *)
            new_value=$(openssl rand -base64 24)
            ;;
    esac
    
    # Update in secret store
    doppler secrets set $secret_name="$new_value"
    
    # Rolling restart of applications
    kubectl rollout restart deployment/freecad-api
    kubectl rollout restart deployment/freecad-worker
    kubectl rollout restart deployment/freecad-worker-freecad
    
    # Verify health
    kubectl rollout status deployment/freecad-api --timeout=300s
    
    # Update monitoring hashes
    echo $new_value | sha256sum | redis-cli set "secret:$secret_name:hash"
    
    echo "SUCCESS: $secret_name rotated successfully"
}

# Usage: ./emergency_rotate.sh SECRET_KEY
emergency_rotate $1
```

## Monitoring Dashboard

### Grafana Secret Security Dashboard
```json
{
  "dashboard": {
    "title": "Secret Security Monitoring",
    "panels": [
      {
        "title": "Secret Access Attempts",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(kubernetes_audit_total{verb=\"get\",objectRef_resource=\"secrets\"}[5m])"
          }
        ]
      },
      {
        "title": "Failed Secret Access",
        "type": "singlestat",
        "targets": [
          {
            "expr": "increase(kubernetes_secret_access_failures_total[1h])"
          }
        ]
      },
      {
        "title": "Secret Rotation Status",
        "type": "table",
        "targets": [
          {
            "expr": "secret_last_rotated_timestamp"
          }
        ]
      }
    ]
  }
}
```

---

## Sonuç

Bu secret yönetimi stratejisi, CNC AI Suite platformunun güvenliğini en üst düzeyde tutmak için tasarlanmıştır. Tüm team üyelerinin bu dokümantasyonu okuması ve uygulaması kritik öneme sahiptir.

**Kritik Hatırlatmalar:**
- ❌ **ASLA** secret'ları git repository'sine commit etmeyin
- ❌ **ASLA** .env dosyalarını production ortamında kullanmayın  
- ❌ **ASLA** secret'ları plain text olarak log'lamayın
- ✅ **HER ZAMAN** external secret management kullanın
- ✅ **HER ZAMAN** secret rotation yapın
- ✅ **HER ZAMAN** audit trail tutun

Sorularınız için: security-team@company.com