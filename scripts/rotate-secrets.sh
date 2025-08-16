#!/bin/bash
# =================================================================================
# SECRET ROTATION SCRIPT - CNC AI Suite
# =================================================================================
# Bu script production güvenliği için düzenli secret rotation yapar
#
# KULLANIM:
#   ./scripts/rotate-secrets.sh [secret-name] [environment] [secret-manager]
#
# PARAMETRELER:
#   secret-name: all|secret-key|database|storage|api-keys
#   environment: dev|test|staging|prod
#   secret-manager: doppler|vault|azure|k8s
#
# ÖRNEKLER:
#   ./scripts/rotate-secrets.sh secret-key prod doppler
#   ./scripts/rotate-secrets.sh all staging vault
# =================================================================================

set -euo pipefail

# Renkli output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Parameters
SECRET_NAME=${1:-all}
ENVIRONMENT=${2:-prod}
SECRET_MANAGER=${3:-doppler}
PROJECT_ROOT=$(dirname $(dirname $(realpath $0)))

# Backup directory
BACKUP_DIR="$PROJECT_ROOT/.secret-backups/$(date +%Y%m%d_%H%M%S)"
mkdir -p $BACKUP_DIR

log_info "Starting secret rotation for: $SECRET_NAME in $ENVIRONMENT using $SECRET_MANAGER"

# Security check - require confirmation for production
confirm_production() {
    if [[ "$ENVIRONMENT" == "prod" ]]; then
        log_warning "You are about to rotate secrets in PRODUCTION environment!"
        read -p "Are you sure? Type 'YES' to continue: " confirmation
        if [[ "$confirmation" != "YES" ]]; then
            log_error "Secret rotation aborted"
            exit 1
        fi
    fi
}

# Backup current secrets
backup_secrets() {
    log_info "Backing up current secrets..."
    
    case $SECRET_MANAGER in
        doppler)
            doppler secrets download --no-file --format env > "$BACKUP_DIR/secrets.env"
            ;;
        vault)
            vault kv get -format=json secret/freecad/$ENVIRONMENT > "$BACKUP_DIR/vault-secrets.json"
            ;;
        azure)
            VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
            az keyvault secret list --vault-name $VAULT_NAME --query '[].{name:name,value:value}' > "$BACKUP_DIR/azure-secrets.json"
            ;;
        k8s)
            kubectl get secret freecad-secrets -n freecad-$ENVIRONMENT -o yaml > "$BACKUP_DIR/k8s-secrets.yaml"
            ;;
    esac
    
    log_success "Secrets backed up to: $BACKUP_DIR"
}

# Generate new secret value
generate_secret() {
    local secret_type=$1
    
    case $secret_type in
        secret-key|SECRET_KEY)
            # JWT signing key - 32 bytes base64
            openssl rand -base64 32
            ;;
        database-password|POSTGRES_PASSWORD)
            # Strong database password - 24 characters
            openssl rand -base64 24 | tr -d "=+/" | cut -c1-24
            ;;
        storage-password|MINIO_ROOT_PASSWORD)
            # Storage password - 20 characters
            openssl rand -base64 20 | tr -d "=+/" | cut -c1-20
            ;;
        encryption-key|ENCRYPTION_KEY)
            # Data encryption key - 32 bytes base64
            openssl rand -base64 32
            ;;
        *)
            # Generic secret - 24 characters
            openssl rand -base64 24 | tr -d "=+/" | cut -c1-24
            ;;
    esac
}

# Rotate JWT secret key
rotate_secret_key() {
    log_info "Rotating JWT secret key..."
    
    NEW_SECRET_KEY=$(generate_secret "secret-key")
    
    case $SECRET_MANAGER in
        doppler)
            doppler secrets set SECRET_KEY="$NEW_SECRET_KEY"
            ;;
        vault)
            vault kv patch secret/freecad/$ENVIRONMENT secret_key="$NEW_SECRET_KEY"
            ;;
        azure)
            VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
            az keyvault secret set --vault-name $VAULT_NAME --name "secret-key" --value "$NEW_SECRET_KEY"
            ;;
        k8s)
            kubectl patch secret freecad-secrets -n freecad-$ENVIRONMENT --type='json' \
                -p='[{"op": "replace", "path": "/data/secret-key", "value": "'$(echo -n $NEW_SECRET_KEY | base64 -w 0)'"}]'
            ;;
    esac
    
    log_success "JWT secret key rotated"
}

# Rotate database credentials
rotate_database_credentials() {
    log_info "Rotating database credentials..."
    
    NEW_DB_PASSWORD=$(generate_secret "database-password")
    
    # First, create new user in database
    log_info "Creating new database user..."
    
    # Get current credentials for connection
    case $SECRET_MANAGER in
        doppler)
            CURRENT_DB_PASSWORD=$(doppler secrets get POSTGRES_PASSWORD --plain)
            ;;
        vault)
            CURRENT_DB_PASSWORD=$(vault kv get -field=postgres_password secret/freecad/$ENVIRONMENT)
            ;;
        azure)
            VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
            CURRENT_DB_PASSWORD=$(az keyvault secret show --vault-name $VAULT_NAME --name "postgres-password" --query "value" -o tsv)
            ;;
        k8s)
            CURRENT_DB_PASSWORD=$(kubectl get secret freecad-secrets -n freecad-$ENVIRONMENT -o jsonpath='{.data.postgres-password}' | base64 -d)
            ;;
    esac
    
    # Connect to database and update password
    PGPASSWORD=$CURRENT_DB_PASSWORD psql -h postgres -U freecad_$ENVIRONMENT -d freecad_$ENVIRONMENT -c \
        "ALTER USER freecad_$ENVIRONMENT PASSWORD '$NEW_DB_PASSWORD';"
    
    # Update secret store
    case $SECRET_MANAGER in
        doppler)
            doppler secrets set POSTGRES_PASSWORD="$NEW_DB_PASSWORD"
            ;;
        vault)
            vault kv patch secret/freecad/$ENVIRONMENT postgres_password="$NEW_DB_PASSWORD"
            ;;
        azure)
            az keyvault secret set --vault-name $VAULT_NAME --name "postgres-password" --value "$NEW_DB_PASSWORD"
            ;;
        k8s)
            kubectl patch secret freecad-secrets -n freecad-$ENVIRONMENT --type='json' \
                -p='[{"op": "replace", "path": "/data/postgres-password", "value": "'$(echo -n $NEW_DB_PASSWORD | base64 -w 0)'"}]'
            ;;
    esac
    
    log_success "Database credentials rotated"
}

# Rotate storage credentials
rotate_storage_credentials() {
    log_info "Rotating storage credentials..."
    
    NEW_STORAGE_PASSWORD=$(generate_secret "storage-password")
    
    # Update MinIO/S3 credentials
    case $SECRET_MANAGER in
        doppler)
            doppler secrets set MINIO_ROOT_PASSWORD="$NEW_STORAGE_PASSWORD"
            doppler secrets set AWS_SECRET_ACCESS_KEY="$NEW_STORAGE_PASSWORD"
            ;;
        vault)
            vault kv patch secret/freecad/$ENVIRONMENT \
                minio_root_password="$NEW_STORAGE_PASSWORD" \
                aws_secret_access_key="$NEW_STORAGE_PASSWORD"
            ;;
        azure)
            VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
            az keyvault secret set --vault-name $VAULT_NAME --name "minio-root-password" --value "$NEW_STORAGE_PASSWORD"
            az keyvault secret set --vault-name $VAULT_NAME --name "aws-secret-access-key" --value "$NEW_STORAGE_PASSWORD"
            ;;
        k8s)
            kubectl patch secret freecad-secrets -n freecad-$ENVIRONMENT --type='json' \
                -p='[{"op": "replace", "path": "/data/minio-root-password", "value": "'$(echo -n $NEW_STORAGE_PASSWORD | base64 -w 0)'"}]'
            ;;
    esac
    
    log_success "Storage credentials rotated"
}

# Rotate API keys (manual process)
rotate_api_keys() {
    log_warning "API key rotation requires manual intervention:"
    echo "1. OpenAI API Key: Rotate in OpenAI dashboard"
    echo "2. Google OAuth: Rotate in Google Cloud Console"
    echo "3. Azure OpenAI: Rotate in Azure portal"
    echo ""
    echo "After manual rotation, update secrets with:"
    
    case $SECRET_MANAGER in
        doppler)
            echo "doppler secrets set OPENAI_API_KEY='new-key'"
            echo "doppler secrets set GOOGLE_CLIENT_SECRET='new-secret'"
            ;;
        vault)
            echo "vault kv patch secret/freecad/$ENVIRONMENT openai_api_key='new-key'"
            ;;
        azure)
            echo "az keyvault secret set --vault-name $VAULT_NAME --name 'openai-api-key' --value 'new-key'"
            ;;
        k8s)
            echo "kubectl patch secret freecad-secrets -n freecad-$ENVIRONMENT ..."
            ;;
    esac
}

# Rolling restart of applications
restart_applications() {
    log_info "Restarting applications to pick up new secrets..."
    
    if command -v kubectl &> /dev/null; then
        # Kubernetes deployment restart
        kubectl rollout restart deployment/freecad-api -n freecad-$ENVIRONMENT
        kubectl rollout restart deployment/freecad-worker -n freecad-$ENVIRONMENT
        kubectl rollout restart deployment/freecad-worker-freecad -n freecad-$ENVIRONMENT
        kubectl rollout restart deployment/freecad-worker-sim -n freecad-$ENVIRONMENT
        
        # Wait for rollout to complete
        kubectl rollout status deployment/freecad-api -n freecad-$ENVIRONMENT --timeout=300s
        
        log_success "Kubernetes deployments restarted"
    elif command -v docker-compose &> /dev/null; then
        # Docker Compose restart
        cd $PROJECT_ROOT
        docker-compose restart api worker worker-freecad worker-sim
        
        log_success "Docker services restarted"
    else
        log_warning "Manual application restart required"
    fi
}

# Verify rotation success
verify_rotation() {
    log_info "Verifying secret rotation..."
    
    # Test application health
    local api_url="http://localhost:8000"
    if [[ "$ENVIRONMENT" == "prod" ]]; then
        api_url="https://api.freecad.company.com"
    fi
    
    # Wait for services to be ready
    sleep 30
    
    # Health check
    if curl -f "$api_url/api/v1/healthz" &> /dev/null; then
        log_success "Application health check passed"
    else
        log_error "Application health check failed - rollback may be required"
        return 1
    fi
    
    # Test database connection
    if curl -f "$api_url/api/v1/ready" &> /dev/null; then
        log_success "Database connectivity verified"
    else
        log_error "Database connection failed"
        return 1
    fi
    
    log_success "Secret rotation verification completed"
}

# Rollback function in case of failure
rollback_secrets() {
    log_error "Rolling back secrets due to failure..."
    
    case $SECRET_MANAGER in
        doppler)
            if [[ -f "$BACKUP_DIR/secrets.env" ]]; then
                while IFS='=' read -r key value; do
                    [[ $key =~ ^[[:space:]]*# ]] && continue  # Skip comments
                    [[ -z "$key" ]] && continue  # Skip empty lines
                    doppler secrets set "$key=$value"
                done < "$BACKUP_DIR/secrets.env"
            fi
            ;;
        vault)
            if [[ -f "$BACKUP_DIR/vault-secrets.json" ]]; then
                # Restore from backup (simplified)
                log_warning "Manual vault secret restoration required from: $BACKUP_DIR/vault-secrets.json"
            fi
            ;;
        azure|k8s)
            log_warning "Manual secret restoration required from: $BACKUP_DIR"
            ;;
    esac
    
    restart_applications
    log_info "Rollback completed"
}

# Main rotation logic
perform_rotation() {
    case $SECRET_NAME in
        all)
            rotate_secret_key
            rotate_database_credentials
            rotate_storage_credentials
            log_info "Manual API key rotation required"
            rotate_api_keys
            ;;
        secret-key|SECRET_KEY)
            rotate_secret_key
            ;;
        database|POSTGRES_PASSWORD)
            rotate_database_credentials
            ;;
        storage|MINIO_ROOT_PASSWORD)
            rotate_storage_credentials
            ;;
        api-keys)
            rotate_api_keys
            return 0  # No restart needed for manual process
            ;;
        *)
            log_error "Unknown secret name: $SECRET_NAME"
            log_info "Valid options: all, secret-key, database, storage, api-keys"
            exit 1
            ;;
    esac
}

# Audit logging
log_rotation_audit() {
    local status=$1
    local audit_log="$PROJECT_ROOT/logs/secret-rotation.log"
    mkdir -p "$(dirname $audit_log)"
    
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) | $ENVIRONMENT | $SECRET_NAME | $SECRET_MANAGER | $status | $(whoami) | $(hostname)" >> "$audit_log"
}

# Main execution
main() {
    local exit_code=0
    
    log_info "Secret rotation started at $(date)"
    
    # Validation
    if [[ "$ENVIRONMENT" == "prod" ]]; then
        confirm_production
    fi
    
    # Pre-rotation backup
    backup_secrets
    
    # Perform rotation
    if perform_rotation; then
        log_success "Secret rotation completed"
        
        # Skip restart for manual API key rotation
        if [[ "$SECRET_NAME" != "api-keys" ]]; then
            restart_applications
            
            # Verify success
            if verify_rotation; then
                log_success "Secret rotation verification passed"
                log_rotation_audit "SUCCESS"
            else
                log_error "Secret rotation verification failed"
                rollback_secrets
                log_rotation_audit "ROLLBACK"
                exit_code=1
            fi
        else
            log_rotation_audit "MANUAL_API_KEYS"
        fi
    else
        log_error "Secret rotation failed"
        rollback_secrets
        log_rotation_audit "FAILED"
        exit_code=1
    fi
    
    log_info "Secret rotation finished at $(date)"
    
    # Cleanup old backups (keep last 10)
    find "$PROJECT_ROOT/.secret-backups" -type d -name "20*" | sort -r | tail -n +11 | xargs rm -rf
    
    exit $exit_code
}

# Trap to ensure cleanup on failure
trap 'log_error "Script interrupted"; log_rotation_audit "INTERRUPTED"; exit 1' INT TERM

# Run main function
main "$@"