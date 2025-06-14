#!/bin/bash
# =============================================================================
# GitLab CI/CD Helper Scripts
# =============================================================================

# =============================================================================
# Container Registry Setup Script
# =============================================================================
setup_registry() {
    echo "Setting up GitLab Container Registry..."

    # Enable Container Registry in GitLab project settings
    echo "1. Go to your GitLab project settings"
    echo "2. Navigate to General > Visibility, project features, permissions"
    echo "3. Enable 'Container Registry'"
    echo "4. Save changes"

    # Login to registry locally for testing
    if [ -n "$CI_REGISTRY_PASSWORD" ]; then
        echo $CI_REGISTRY_PASSWORD | docker login -u $CI_REGISTRY_USER --password-stdin $CI_REGISTRY
        echo "✅ Successfully logged into GitLab Container Registry"
    else
        echo "❌ CI_REGISTRY_PASSWORD not set"
        echo "Set up GitLab Deploy Token or use your personal access token"
    fi
}

# =============================================================================
# Environment Variables Setup
# =============================================================================
setup_variables() {
    echo "Setting up GitLab CI/CD Variables..."
    echo "Go to your GitLab project: Settings > CI/CD > Variables"
    echo ""
    echo "Required Variables:"
    echo "==================="
    echo "CI_REGISTRY_USER: \$CI_REGISTRY_USER (auto-provided)"
    echo "CI_REGISTRY_PASSWORD: \$CI_REGISTRY_PASSWORD (auto-provided)"
    echo "CI_REGISTRY: \$CI_REGISTRY (auto-provided)"
    echo ""
    echo "Optional Variables:"
    echo "=================="
    echo "SLACK_WEBHOOK_URL: Your Slack webhook for notifications"
    echo "KUBECONFIG: Base64 encoded kubeconfig for Kubernetes deployments"
    echo "DOCKER_HUB_USERNAME: For Docker Hub deployments (optional)"
    echo "DOCKER_HUB_PASSWORD: For Docker Hub deployments (optional)"
    echo ""
    echo "Environment-specific variables:"
    echo "DEV_DB_PASSWORD: Development database password"
    echo "STAGING_DB_PASSWORD: Staging database password"
    echo "PROD_DB_PASSWORD: Production database password"
    echo "PROD_SECRET_KEY: Production Flask secret key"
    echo "PROD_MASTER_KEY: Production master encryption key"
}

# =============================================================================
# GitLab Runner Registration
# =============================================================================
register_runner() {
    echo "Registering GitLab Runner..."
    echo "1. Install GitLab Runner on your server"
    echo "2. Get registration token from GitLab project: Settings > CI/CD > Runners"
    echo "3. Run registration command:"
    echo ""
    echo "sudo gitlab-runner register \\"
    echo "  --url https://gitlab.com/ \\"
    echo "  --registration-token YOUR_TOKEN \\"
    echo "  --executor docker \\"
    echo "  --description \"TrakBridge Docker Runner\" \\"
    echo "  --docker-image docker:24.0.5 \\"
    echo "  --docker-privileged \\"
    echo "  --docker-volumes /var/run/docker.sock:/var/run/docker.sock"
}

# =============================================================================
# Deploy Key Setup for Private Repositories
# =============================================================================
setup_deploy_keys() {
    echo "Setting up Deploy Keys for private repositories..."

    # Generate SSH key pair
    ssh-keygen -t rsa -b 4096 -f ./deploy_key -N ""

    echo "1. Add the public key to your GitLab project:"
    echo "   Settings > Repository > Deploy Keys"
    echo ""
    cat ./deploy_key.pub
    echo ""
    echo "2. Add the private key as a CI/CD variable:"
    echo "   Settings > CI/CD > Variables"
    echo "   Variable: SSH_PRIVATE_KEY"
    echo "   Value: (paste the private key content)"
    echo ""
    cat ./deploy_key

    # Clean up keys (don't leave them in the repo)
    rm -f ./deploy_key ./deploy_key.pub
}

# =============================================================================
# Docker Registry Cleanup Script
# =============================================================================
cleanup_registry() {
    local PROJECT_ID="$1"
    local REGISTRY_PATH="$2"
    local KEEP_COUNT="${3:-10}"

    if [ -z "$PROJECT_ID" ] || [ -z "$REGISTRY_PATH" ]; then
        echo "Usage: cleanup_registry <project_id> <registry_path> [keep_count]"
        echo "Example: cleanup_registry 12345 trakbridge 10"
        return 1
    fi

    echo "Cleaning up registry: $REGISTRY_PATH (keeping latest $KEEP_COUNT images)"

    # This requires GitLab API token with appropriate permissions
    curl --header "PRIVATE-TOKEN: $GITLAB_API_TOKEN" \
         --request DELETE \
         "https://gitlab.com/api/v4/projects/$PROJECT_ID/registry/repositories/$REGISTRY_PATH/tags?keep_n=$KEEP_COUNT&name_regex=.*"
}

# =============================================================================
# Local Development Container Registry Test
# =============================================================================
test_registry_locally() {
    echo "Testing container registry locally..."

    # Build test image
    docker build -t test-registry-push:latest .

    # Tag for registry
    docker tag test-registry-push:latest $CI_REGISTRY_IMAGE/test:latest

    # Push to registry
    docker push $CI_REGISTRY_IMAGE/test:latest

    # Pull from registry
    docker pull $CI_REGISTRY_IMAGE/test:latest

    echo "✅ Registry test completed successfully"

    # Cleanup
    docker rmi test-registry-push:latest $CI_REGISTRY_IMAGE/test:latest
}

# =============================================================================
# Kubernetes Secret Management
# =============================================================================
setup_k8s_secrets() {
    local NAMESPACE="${1:-trakbridge-prod}"

    echo "Setting up Kubernetes secrets for namespace: $NAMESPACE"

    # Create namespace if it doesn't exist
    kubectl create namespace $NAMESPACE --dry-run=client -o yaml | kubectl apply -f -

    # Create registry secret for pulling images
    kubectl create secret docker-registry gitlab-registry \
        --docker-server=$CI_REGISTRY \
        --docker-username=$CI_REGISTRY_USER \
        --docker-password=$CI_REGISTRY_PASSWORD \
        --namespace=$NAMESPACE

    # Create application secrets
    kubectl create secret generic trakbridge-secrets \
        --from-literal=db-password="$PROD_DB_PASSWORD" \
        --from-literal=secret-key="$PROD_SECRET_KEY" \
        --from-literal=master-key="$PROD_MASTER_KEY" \
        --namespace=$NAMESPACE

    echo "✅ Kubernetes secrets created successfully"
}

# =============================================================================
# Pipeline Status Webhook
# =============================================================================
setup_webhook() {
    local WEBHOOK_URL="$1"

    if [ -z "$WEBHOOK_URL" ]; then
        echo "Usage: setup_webhook <webhook_url>"
        return 1
    fi

    echo "Setting up pipeline webhook..."
    echo "Add this webhook URL to your GitLab project:"
    echo "Settings > Webhooks"
    echo ""
    echo "URL: $WEBHOOK_URL"
    echo "Trigger: Pipeline events, Job events"
    echo "Secret Token: (optional but recommended)"
}

# =============================================================================
# Main Menu
# =============================================================================
show_menu() {
    echo "GitLab CI/CD Setup Helper"
    echo "========================="
    echo "1. Setup Container Registry"
    echo "2. Setup CI/CD Variables"
    echo "3. Register GitLab Runner"
    echo "4. Setup Deploy Keys"
    echo "5. Test Registry Locally"
    echo "6. Setup Kubernetes Secrets"
    echo "7. Cleanup Registry"
    echo "8. Setup Webhook"
    echo "9. Exit"
    echo ""
    read -p "Choose an option (1-9): " choice

    case $choice in
        1) setup_registry ;;
        2) setup_variables ;;
        3) register_runner ;;
        4) setup_deploy_keys ;;
        5) test_registry_locally ;;
        6) read -p "Enter namespace (default: trakbridge-prod): " ns; setup_k8s_secrets "${ns:-trakbridge-prod}" ;;
        7) read -p "Enter project ID: " pid; read -p "Enter registry path: " path; cleanup_registry "$pid" "$path" ;;
        8) read -p "Enter webhook URL: " url; setup_webhook "$url" ;;
        9) exit 0 ;;
        *) echo "Invalid option"; show_menu ;;
    esac
}

# =============================================================================
# Script Entry Point
# =============================================================================
if [ "$#" -eq 0 ]; then
    show_menu
else
    case "$1" in
        setup-registry) setup_registry ;;
        setup-variables) setup_variables ;;
        register-runner) register_runner ;;
        setup-deploy-keys) setup_deploy_keys ;;
        test-registry) test_registry_locally ;;
        setup-k8s-secrets) setup_k8s_secrets "$2" ;;
        cleanup-registry) cleanup_registry "$2" "$3" "$4" ;;
        setup-webhook) setup_webhook "$2" ;;
        *) echo "Unknown command: $1"; show_menu ;;
    esac
fi