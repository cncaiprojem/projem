#!/bin/bash
# =================================================================================
# SECRET SETUP SCRIPT - CNC AI Suite
# =================================================================================
# Bu script güvenli secret yönetimi için gerekli araçları kurar ve yapılandırır
# 
# KULLANIM:
#   ./scripts/setup-secrets.sh [environment] [secret-manager]
#   
# PARAMETRELER:
#   environment: dev|test|staging|prod
#   secret-manager: doppler|vault|azure|k8s
#
# ÖRNEKLER:
#   ./scripts/setup-secrets.sh dev doppler
#   ./scripts/setup-secrets.sh prod vault
# =================================================================================

set -euo pipefail

# Renkli output için
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Default values
ENVIRONMENT=${1:-dev}
SECRET_MANAGER=${2:-doppler}
PROJECT_ROOT=$(dirname $(dirname $(realpath $0)))

log_info "Setting up secrets for environment: $ENVIRONMENT using $SECRET_MANAGER"

# Validate environment
validate_environment() {
    case $ENVIRONMENT in
        dev|test|staging|prod)
            log_success "Valid environment: $ENVIRONMENT"
            ;;
        *)
            log_error "Invalid environment: $ENVIRONMENT. Must be one of: dev, test, staging, prod"
            exit 1
            ;;
    esac
}

# Install Doppler CLI
install_doppler() {
    log_info "Installing Doppler CLI..."
    
    if command -v doppler &> /dev/null; then
        log_warning "Doppler already installed: $(doppler --version)"
        return
    fi
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        curl -Ls https://cli.doppler.com/install.sh | sh
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew install dopplerhq/cli/doppler
    elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "win32" ]]; then
        log_error "Windows detected. Please install Doppler manually: https://docs.doppler.com/docs/install-cli"
        exit 1
    fi
    
    log_success "Doppler CLI installed successfully"
}

# Setup Doppler project
setup_doppler() {
    log_info "Setting up Doppler project for $ENVIRONMENT..."
    
    install_doppler
    
    # Login check
    if ! doppler me &> /dev/null; then
        log_warning "Please login to Doppler first:"
        echo "doppler login"
        exit 1
    fi
    
    # Create project if not exists
    PROJECT_NAME="freecad-cnc-suite"
    
    if ! doppler projects get $PROJECT_NAME &> /dev/null; then
        log_info "Creating Doppler project: $PROJECT_NAME"
        doppler projects create $PROJECT_NAME --description "CNC AI Suite - FreeCAD Platform"
    fi
    
    # Setup environment
    cd $PROJECT_ROOT
    doppler setup --project $PROJECT_NAME --config $ENVIRONMENT
    
    # Set essential secrets for development
    if [[ "$ENVIRONMENT" == "dev" ]]; then
        log_info "Setting up development secrets..."
        
        # Generate secure secret key
        SECRET_KEY=$(openssl rand -base64 32)
        doppler secrets set SECRET_KEY="$SECRET_KEY" --silent
        
        # Set mock values for development
        doppler secrets set OPENAI_API_KEY="sk-dev-mock-key-for-testing-only" --silent
        doppler secrets set POSTGRES_PASSWORD="dev_secure_password_$(date +%s)" --silent
        doppler secrets set MINIO_ROOT_PASSWORD="dev_minio_password_$(date +%s)" --silent
        
        log_success "Development secrets configured"
    fi
    
    log_success "Doppler setup completed for $ENVIRONMENT"
}

# Install HashiCorp Vault
install_vault() {
    log_info "Installing HashiCorp Vault..."
    
    if command -v vault &> /dev/null; then
        log_warning "Vault already installed: $(vault version)"
        return
    fi
    
    if [[ "$OSTYPE" == "linux-gnu"* ]]; then
        wget -O- https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
        echo "deb [signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com $(lsb_release -cs) main" | sudo tee /etc/apt/sources.list.d/hashicorp.list
        sudo apt update && sudo apt install vault
    elif [[ "$OSTYPE" == "darwin"* ]]; then
        brew tap hashicorp/tap
        brew install hashicorp/tap/vault
    else
        log_error "Unsupported OS for automatic Vault installation"
        exit 1
    fi
    
    log_success "Vault installed successfully"
}

# Setup HashiCorp Vault
setup_vault() {
    log_info "Setting up HashiCorp Vault for $ENVIRONMENT..."
    
    install_vault
    
    # Check if Vault server is running
    if ! vault status &> /dev/null; then
        log_error "Vault server is not running. Please start Vault server first:"
        echo "vault server -dev"
        exit 1
    fi
    
    # Create secrets for environment
    VAULT_PATH="secret/freecad/$ENVIRONMENT"
    
    log_info "Creating secrets at path: $VAULT_PATH"
    
    if [[ "$ENVIRONMENT" == "dev" ]]; then
        SECRET_KEY=$(openssl rand -base64 32)
        POSTGRES_PASSWORD="dev_secure_password_$(date +%s)"
        MINIO_PASSWORD="dev_minio_password_$(date +%s)"
        
        vault kv put $VAULT_PATH \
            secret_key="$SECRET_KEY" \
            openai_api_key="sk-dev-mock-key-for-testing-only" \
            postgres_password="$POSTGRES_PASSWORD" \
            minio_root_password="$MINIO_PASSWORD"
    fi
    
    log_success "Vault setup completed for $ENVIRONMENT"
}

# Setup Azure Key Vault
setup_azure() {
    log_info "Setting up Azure Key Vault for $ENVIRONMENT..."
    
    # Check Azure CLI
    if ! command -v az &> /dev/null; then
        log_error "Azure CLI not found. Please install: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi
    
    # Check login
    if ! az account show &> /dev/null; then
        log_warning "Please login to Azure first:"
        echo "az login"
        exit 1
    fi
    
    VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
    RESOURCE_GROUP="freecad-cnc-$ENVIRONMENT-rg"
    
    log_info "Creating Key Vault: $VAULT_NAME"
    
    # Create resource group if not exists
    az group create --name $RESOURCE_GROUP --location "East US" --output none
    
    # Create Key Vault
    az keyvault create \
        --name $VAULT_NAME \
        --resource-group $RESOURCE_GROUP \
        --location "East US" \
        --sku Premium \
        --output none
    
    # Set secrets for development
    if [[ "$ENVIRONMENT" == "dev" ]]; then
        SECRET_KEY=$(openssl rand -base64 32)
        
        az keyvault secret set --vault-name $VAULT_NAME --name "secret-key" --value "$SECRET_KEY" --output none
        az keyvault secret set --vault-name $VAULT_NAME --name "openai-api-key" --value "sk-dev-mock-key-for-testing-only" --output none
        az keyvault secret set --vault-name $VAULT_NAME --name "postgres-password" --value "dev_secure_password_$(date +%s)" --output none
    fi
    
    log_success "Azure Key Vault setup completed"
}

# Setup Kubernetes Secrets with External Secrets Operator
setup_k8s_secrets() {
    log_info "Setting up Kubernetes secrets for $ENVIRONMENT..."
    
    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl not found. Please install kubectl"
        exit 1
    fi
    
    # Check cluster access
    if ! kubectl cluster-info &> /dev/null; then
        log_error "Cannot connect to Kubernetes cluster"
        exit 1
    fi
    
    # Install External Secrets Operator
    log_info "Installing External Secrets Operator..."
    kubectl apply -f https://raw.githubusercontent.com/external-secrets/external-secrets/main/deploy/crds/bundle.yaml
    kubectl apply -f https://raw.githubusercontent.com/external-secrets/external-secrets/main/deploy/charts/external-secrets/templates/rbac.yaml
    kubectl apply -f https://raw.githubusercontent.com/external-secrets/external-secrets/main/deploy/charts/external-secrets/templates/deployment.yaml
    
    # Create namespace
    kubectl create namespace freecad-$ENVIRONMENT --dry-run=client -o yaml | kubectl apply -f -
    
    # Generate base secret for development
    if [[ "$ENVIRONMENT" == "dev" ]]; then
        SECRET_KEY=$(openssl rand -base64 32)
        
        kubectl create secret generic freecad-secrets \
            --namespace=freecad-$ENVIRONMENT \
            --from-literal=secret-key="$SECRET_KEY" \
            --from-literal=openai-api-key="sk-dev-mock-key-for-testing-only" \
            --from-literal=postgres-password="dev_secure_password_$(date +%s)" \
            --dry-run=client -o yaml | kubectl apply -f -
    fi
    
    log_success "Kubernetes secrets setup completed"
}

# Generate environment file from secrets
generate_env_file() {
    log_info "Generating .env.$ENVIRONMENT file..."
    
    ENV_FILE="$PROJECT_ROOT/.env.$ENVIRONMENT"
    
    case $SECRET_MANAGER in
        doppler)
            doppler secrets download --no-file --format env > $ENV_FILE
            ;;
        vault)
            vault kv get -format=json secret/freecad/$ENVIRONMENT | jq -r '.data.data | to_entries[] | "\(.key | ascii_upcase)=\(.value)"' > $ENV_FILE
            ;;
        azure)
            log_warning "Azure Key Vault requires manual environment file generation"
            ;;
        k8s)
            kubectl get secret freecad-secrets -n freecad-$ENVIRONMENT -o jsonpath='{.data}' | jq -r 'to_entries[] | "\(.key | ascii_upcase)=\(.value | @base64d)"' > $ENV_FILE
            ;;
    esac
    
    if [[ -f $ENV_FILE ]]; then
        log_success "Environment file generated: $ENV_FILE"
        log_warning "Remember to add this file to .gitignore if it contains real secrets!"
    fi
}

# Validate secrets
validate_secrets() {
    log_info "Validating secrets configuration..."
    
    case $SECRET_MANAGER in
        doppler)
            if doppler secrets get SECRET_KEY &> /dev/null; then
                log_success "Doppler secrets validation passed"
            else
                log_error "Doppler secrets validation failed"
                exit 1
            fi
            ;;
        vault)
            if vault kv get secret/freecad/$ENVIRONMENT &> /dev/null; then
                log_success "Vault secrets validation passed"
            else
                log_error "Vault secrets validation failed"
                exit 1
            fi
            ;;
        azure)
            VAULT_NAME="freecad-cnc-$ENVIRONMENT-kv"
            if az keyvault secret show --vault-name $VAULT_NAME --name "secret-key" &> /dev/null; then
                log_success "Azure Key Vault validation passed"
            else
                log_error "Azure Key Vault validation failed"
                exit 1
            fi
            ;;
        k8s)
            if kubectl get secret freecad-secrets -n freecad-$ENVIRONMENT &> /dev/null; then
                log_success "Kubernetes secrets validation passed"
            else
                log_error "Kubernetes secrets validation failed"
                exit 1
            fi
            ;;
    esac
}

# Main execution
main() {
    log_info "Starting secret setup for CNC AI Suite..."
    
    validate_environment
    
    case $SECRET_MANAGER in
        doppler)
            setup_doppler
            ;;
        vault)
            setup_vault
            ;;
        azure)
            setup_azure
            ;;
        k8s)
            setup_k8s_secrets
            ;;
        *)
            log_error "Invalid secret manager: $SECRET_MANAGER. Must be one of: doppler, vault, azure, k8s"
            exit 1
            ;;
    esac
    
    validate_secrets
    
    if [[ "$ENVIRONMENT" == "dev" ]] || [[ "$ENVIRONMENT" == "test" ]]; then
        generate_env_file
    fi
    
    log_success "Secret setup completed successfully!"
    log_info "Next steps:"
    echo "1. Review the generated secrets"
    echo "2. Test application startup with new secrets"
    echo "3. Setup secret rotation schedule"
    echo "4. Configure monitoring and alerting"
}

# Run main function
main "$@"