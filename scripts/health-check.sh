#!/bin/bash

# =============================================================================
# TrakBridge Health Check Script
# =============================================================================
#
# Comprehensive health check script for TrakBridge deployments.
# This script performs various health checks and reports on system status.
#
# Author: Emfour Solutions
# Version: 1.0.0
# =============================================================================

set -euo pipefail

# Script configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Default values
BASE_URL="http://localhost:5000"
TIMEOUT=30
VERBOSE=false
OUTPUT_FORMAT="text"
CHECK_DEPENDENCIES=true
CHECK_PERFORMANCE=false

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Health check results
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0
WARNING_CHECKS=0

# =============================================================================
# Utility Functions
# =============================================================================

log() {
    local level="$1"
    shift
    local message="$*"
    
    case "$level" in
        "PASS")
            echo -e "${GREEN}✅ $message${NC}"
            ((PASSED_CHECKS++))
            ;;
        "FAIL")
            echo -e "${RED}❌ $message${NC}"
            ((FAILED_CHECKS++))
            ;;
        "WARN")
            echo -e "${YELLOW}⚠️  $message${NC}"
            ((WARNING_CHECKS++))
            ;;
        "INFO")
            echo -e "${BLUE}ℹ️  $message${NC}"
            ;;
        "DEBUG")
            if [[ "$VERBOSE" == "true" ]]; then
                echo -e "${BLUE}[DEBUG] $message${NC}"
            fi
            ;;
    esac
    
    ((TOTAL_CHECKS++))
}

show_usage() {
    cat << EOF
TrakBridge Health Check Script

Usage: $0 [OPTIONS]

Options:
    -u, --url URL           Base URL to check (default: http://localhost:5000)
    -t, --timeout SECONDS   Request timeout (default: 30)
    -f, --format FORMAT     Output format (text|json) (default: text)
    -p, --performance       Include performance checks
    -d, --no-dependencies   Skip dependency checks
    -v, --verbose           Enable verbose logging
    -h, --help             Show this help message

Examples:
    $0                                          # Basic health check
    $0 --url http://localhost --performance     # With performance checks
    $0 --format json                           # JSON output
    $0 --url https://staging.example.com       # Check staging environment

EOF
}

# =============================================================================
# Health Check Functions
# =============================================================================

check_basic_connectivity() {
    log "INFO" "Checking basic connectivity..."
    
    if curl -f -s --max-time "$TIMEOUT" "$BASE_URL" > /dev/null 2>&1; then
        log "PASS" "Basic connectivity to $BASE_URL"
    else
        log "FAIL" "Cannot connect to $BASE_URL"
        return 1
    fi
}

check_health_endpoint() {
    log "INFO" "Checking health endpoint..."
    
    local health_url="$BASE_URL/api/health"
    local response
    
    if response=$(curl -f -s --max-time "$TIMEOUT" "$health_url" 2>/dev/null); then
        log "PASS" "Health endpoint responding"
        
        # Parse JSON response if possible
        if command -v jq &> /dev/null; then
            local status=$(echo "$response" | jq -r '.status // "unknown"' 2>/dev/null)
            if [[ "$status" == "healthy" ]]; then
                log "PASS" "Application reports healthy status"
            else
                log "WARN" "Application status: $status"
            fi
        fi
    else
        log "FAIL" "Health endpoint not responding"
        return 1
    fi
}

check_detailed_health() {
    log "INFO" "Checking detailed health endpoint..."
    
    local detailed_url="$BASE_URL/api/health/detailed"
    local response
    
    if response=$(curl -f -s --max-time "$TIMEOUT" "$detailed_url" 2>/dev/null); then
        log "PASS" "Detailed health endpoint responding"
        
        if command -v jq &> /dev/null; then
            # Check database status
            local db_status=$(echo "$response" | jq -r '.checks.database.status // "unknown"' 2>/dev/null)
            if [[ "$db_status" == "healthy" ]]; then
                log "PASS" "Database connection healthy"
            else
                log "WARN" "Database status: $db_status"
            fi
            
            # Check authentication system
            local auth_status=$(echo "$response" | jq -r '.checks.authentication.status // "unknown"' 2>/dev/null)
            if [[ "$auth_status" == "healthy" ]]; then
                log "PASS" "Authentication system healthy"
            else
                log "WARN" "Authentication status: $auth_status"
            fi
        fi
    else
        log "WARN" "Detailed health endpoint not accessible (this might be expected)"
    fi
}

check_authentication() {
    log "INFO" "Checking authentication system..."
    
    local login_url="$BASE_URL/auth/login"
    
    # Check if login page is accessible
    if curl -f -s --max-time "$TIMEOUT" "$login_url" > /dev/null 2>&1; then
        log "PASS" "Authentication login page accessible"
    else
        log "FAIL" "Authentication login page not accessible"
    fi
}

check_static_resources() {
    log "INFO" "Checking static resources..."
    
    local static_resources=(
        "/static/css/bootstrap.min.css"
        "/static/js/jquery.min.js"
        "/favicon.ico"
    )
    
    local failed_resources=0
    
    for resource in "${static_resources[@]}"; do
        local resource_url="$BASE_URL$resource"
        if curl -f -s --max-time "$TIMEOUT" "$resource_url" > /dev/null 2>&1; then
            log "DEBUG" "Static resource accessible: $resource"
        else
            log "DEBUG" "Static resource failed: $resource"
            ((failed_resources++))
        fi
    done
    
    if [[ $failed_resources -eq 0 ]]; then
        log "PASS" "All static resources accessible"
    elif [[ $failed_resources -lt 3 ]]; then
        log "WARN" "$failed_resources static resources failed"
    else
        log "FAIL" "Multiple static resources failed"
    fi
}

check_api_endpoints() {
    log "INFO" "Checking API endpoints..."
    
    local api_endpoints=(
        "/api/health"
        "/api/health/detailed"
    )
    
    local failed_endpoints=0
    
    for endpoint in "${api_endpoints[@]}"; do
        local endpoint_url="$BASE_URL$endpoint"
        if curl -f -s --max-time "$TIMEOUT" "$endpoint_url" > /dev/null 2>&1; then
            log "DEBUG" "API endpoint accessible: $endpoint"
        else
            log "DEBUG" "API endpoint failed: $endpoint"
            ((failed_endpoints++))
        fi
    done
    
    if [[ $failed_endpoints -eq 0 ]]; then
        log "PASS" "All API endpoints accessible"
    elif [[ $failed_endpoints -eq 1 ]]; then
        log "WARN" "1 API endpoint failed"
    else
        log "FAIL" "Multiple API endpoints failed"
    fi
}

check_security_headers() {
    log "INFO" "Checking security headers..."
    
    local headers_response
    if headers_response=$(curl -I -s --max-time "$TIMEOUT" "$BASE_URL" 2>/dev/null); then
        local security_headers=(
            "X-Frame-Options"
            "X-Content-Type-Options"
            "X-XSS-Protection"
        )
        
        local missing_headers=0
        
        for header in "${security_headers[@]}"; do
            if echo "$headers_response" | grep -qi "^$header:"; then
                log "DEBUG" "Security header present: $header"
            else
                log "DEBUG" "Security header missing: $header"
                ((missing_headers++))
            fi
        done
        
        if [[ $missing_headers -eq 0 ]]; then
            log "PASS" "All security headers present"
        elif [[ $missing_headers -lt 2 ]]; then
            log "WARN" "$missing_headers security headers missing"
        else
            log "FAIL" "Multiple security headers missing"
        fi
    else
        log "WARN" "Could not check security headers"
    fi
}

check_performance() {
    if [[ "$CHECK_PERFORMANCE" != "true" ]]; then
        return 0
    fi
    
    log "INFO" "Checking performance metrics..."
    
    # Response time check
    local response_time
    if response_time=$(curl -o /dev/null -s -w '%{time_total}' --max-time "$TIMEOUT" "$BASE_URL" 2>/dev/null); then
        local response_time_ms=$(echo "$response_time * 1000" | bc 2>/dev/null || echo "unknown")
        
        if (( $(echo "$response_time < 1.0" | bc -l 2>/dev/null || echo 0) )); then
            log "PASS" "Response time: ${response_time}s (${response_time_ms}ms)"
        elif (( $(echo "$response_time < 3.0" | bc -l 2>/dev/null || echo 0) )); then
            log "WARN" "Response time: ${response_time}s (${response_time_ms}ms) - could be improved"
        else
            log "FAIL" "Response time: ${response_time}s (${response_time_ms}ms) - too slow"
        fi
    else
        log "WARN" "Could not measure response time"
    fi
    
    # Check if HTTPS is being used
    if [[ "$BASE_URL" == https://* ]]; then
        log "PASS" "Using HTTPS connection"
    else
        log "WARN" "Not using HTTPS (this might be expected for development)"
    fi
}

check_docker_services() {
    if [[ "$CHECK_DEPENDENCIES" != "true" ]]; then
        return 0
    fi
    
    log "INFO" "Checking Docker services..."
    
    if command -v docker &> /dev/null; then
        # Check if any TrakBridge containers are running
        local running_containers
        if running_containers=$(docker ps --filter "name=trakbridge" --format "table {{.Names}}\t{{.Status}}" 2>/dev/null); then
            if [[ -n "$running_containers" && "$running_containers" != "NAMES	STATUS" ]]; then
                log "PASS" "TrakBridge containers are running"
                if [[ "$VERBOSE" == "true" ]]; then
                    echo "$running_containers"
                fi
            else
                log "WARN" "No TrakBridge containers found running"
            fi
        else
            log "WARN" "Could not check Docker containers"
        fi
    else
        log "DEBUG" "Docker not available for container checks"
    fi
}

check_database_connectivity() {
    log "INFO" "Checking database connectivity through application..."
    
    # Try to access an endpoint that requires database
    local db_test_url="$BASE_URL/api/health/detailed"
    local response
    
    if response=$(curl -f -s --max-time "$TIMEOUT" "$db_test_url" 2>/dev/null); then
        if command -v jq &> /dev/null; then
            local db_status=$(echo "$response" | jq -r '.checks.database.status // "unknown"' 2>/dev/null)
            case "$db_status" in
                "healthy")
                    log "PASS" "Database connectivity through application"
                    ;;
                "unhealthy")
                    log "FAIL" "Database connectivity issues"
                    ;;
                *)
                    log "WARN" "Database status unclear: $db_status"
                    ;;
            esac
        else
            log "PASS" "Database endpoint responding (jq not available for detailed status)"
        fi
    else
        log "WARN" "Could not check database connectivity through application"
    fi
}

# =============================================================================
# Report Generation
# =============================================================================

generate_text_report() {
    echo ""
    echo "============================================================="
    echo "TrakBridge Health Check Report"
    echo "============================================================="
    echo "Timestamp: $(date)"
    echo "Target URL: $BASE_URL"
    echo "Timeout: ${TIMEOUT}s"
    echo ""
    echo "Summary:"
    echo "  Total Checks: $TOTAL_CHECKS"
    echo "  Passed: $PASSED_CHECKS"
    echo "  Failed: $FAILED_CHECKS"
    echo "  Warnings: $WARNING_CHECKS"
    echo ""
    
    local overall_status="HEALTHY"
    if [[ $FAILED_CHECKS -gt 0 ]]; then
        overall_status="UNHEALTHY"
    elif [[ $WARNING_CHECKS -gt 3 ]]; then
        overall_status="DEGRADED"
    fi
    
    case "$overall_status" in
        "HEALTHY")
            echo -e "Overall Status: ${GREEN}✅ $overall_status${NC}"
            ;;
        "DEGRADED")
            echo -e "Overall Status: ${YELLOW}⚠️  $overall_status${NC}"
            ;;
        "UNHEALTHY")
            echo -e "Overall Status: ${RED}❌ $overall_status${NC}"
            ;;
    esac
    
    echo "============================================================="
}

generate_json_report() {
    local overall_status="healthy"
    if [[ $FAILED_CHECKS -gt 0 ]]; then
        overall_status="unhealthy"
    elif [[ $WARNING_CHECKS -gt 3 ]]; then
        overall_status="degraded"
    fi
    
    cat << EOF
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "target_url": "$BASE_URL",
  "timeout": $TIMEOUT,
  "overall_status": "$overall_status",
  "summary": {
    "total_checks": $TOTAL_CHECKS,
    "passed": $PASSED_CHECKS,
    "failed": $FAILED_CHECKS,
    "warnings": $WARNING_CHECKS
  },
  "health_score": $(echo "scale=2; ($PASSED_CHECKS * 100) / $TOTAL_CHECKS" | bc 2>/dev/null || echo "0")
}
EOF
}

# =============================================================================
# Main Function
# =============================================================================

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -u|--url)
                BASE_URL="$2"
                shift 2
                ;;
            -t|--timeout)
                TIMEOUT="$2"
                shift 2
                ;;
            -f|--format)
                OUTPUT_FORMAT="$2"
                shift 2
                ;;
            -p|--performance)
                CHECK_PERFORMANCE=true
                shift
                ;;
            -d|--no-dependencies)
                CHECK_DEPENDENCIES=false
                shift
                ;;
            -v|--verbose)
                VERBOSE=true
                shift
                ;;
            -h|--help)
                show_usage
                exit 0
                ;;
            *)
                echo "Unknown option: $1"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # Initialize counters
    TOTAL_CHECKS=0
    PASSED_CHECKS=0
    FAILED_CHECKS=0
    WARNING_CHECKS=0
    
    # Run health checks
    echo "Starting TrakBridge health checks..."
    echo ""
    
    check_basic_connectivity
    check_health_endpoint
    check_detailed_health
    check_authentication
    check_static_resources
    check_api_endpoints
    check_security_headers
    check_performance
    check_docker_services
    check_database_connectivity
    
    # Generate report
    if [[ "$OUTPUT_FORMAT" == "json" ]]; then
        generate_json_report
    else
        generate_text_report
    fi
    
    # Exit with appropriate code
    if [[ $FAILED_CHECKS -gt 0 ]]; then
        exit 1
    elif [[ $WARNING_CHECKS -gt 5 ]]; then
        exit 2
    else
        exit 0
    fi
}

# =============================================================================
# Script Entry Point
# =============================================================================

main "$@"