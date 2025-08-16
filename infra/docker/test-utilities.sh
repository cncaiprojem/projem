#!/bin/bash
# ==============================================================================
# UTILITY DOCKER IMAGES TEST SCRIPT
# ==============================================================================
# Tests all utility Docker images to verify they build and run correctly
# Usage: ./test-utilities.sh
# ==============================================================================

set -e

echo "=========================================="
echo "Testing Utility Docker Images"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

test_image() {
    local image_name=$1
    local test_command=$2
    local expected_pattern=$3
    
    echo -e "\n${YELLOW}Testing ${image_name}...${NC}"
    
    if docker run --rm "${image_name}" ${test_command} 2>&1 | grep -q "${expected_pattern}"; then
        echo -e "${GREEN}✓ ${image_name} test passed${NC}"
        return 0
    else
        echo -e "${RED}✗ ${image_name} test failed${NC}"
        return 1
    fi
}

# Test results tracking
passed=0
failed=0

# Test FFmpeg Utility
echo -e "\n${YELLOW}=== Testing FFmpeg Utility ===${NC}"
if test_image "ffmpeg-utility:6.1" "ffmpeg -version" "ffmpeg version"; then
    ((passed++))
else
    ((failed++))
fi

# Test additional FFmpeg functionality
echo -e "\n${YELLOW}Testing FFmpeg help command...${NC}"
if docker run --rm ffmpeg-utility:6.1 ffmpeg -h 2>&1 | grep -q "usage:"; then
    echo -e "${GREEN}✓ FFmpeg help command works${NC}"
    ((passed++))
else
    echo -e "${RED}✗ FFmpeg help command failed${NC}"
    ((failed++))
fi

# Test ClamAV Utility
echo -e "\n${YELLOW}=== Testing ClamAV Utility ===${NC}"
if test_image "clamav-utility:1.3" "clamscan --version" "ClamAV"; then
    ((passed++))
else
    ((failed++))
fi

# Test ClamAV database
echo -e "\n${YELLOW}Testing ClamAV database...${NC}"
if docker run --rm clamav-utility:1.3 sh -c "ls -la /var/lib/clamav/ | grep -E '(main|daily|bytecode)'" | grep -q "cvd"; then
    echo -e "${GREEN}✓ ClamAV virus database is present${NC}"
    ((passed++))
else
    echo -e "${RED}✗ ClamAV virus database missing${NC}"
    ((failed++))
fi

# Test user permissions
echo -e "\n${YELLOW}=== Testing Security (Non-root execution) ===${NC}"

echo -e "\n${YELLOW}Testing FFmpeg user...${NC}"
if docker run --rm ffmpeg-utility:6.1 whoami | grep -q "ffmpeg"; then
    echo -e "${GREEN}✓ FFmpeg runs as non-root user${NC}"
    ((passed++))
else
    echo -e "${RED}✗ FFmpeg user test failed${NC}"
    ((failed++))
fi

echo -e "\n${YELLOW}Testing ClamAV user...${NC}"
if docker run --rm clamav-utility:1.3 whoami | grep -q "clamav"; then
    echo -e "${GREEN}✓ ClamAV runs as non-root user${NC}"
    ((passed++))
else
    echo -e "${RED}✗ ClamAV user test failed${NC}"
    ((failed++))
fi

# Test health checks
echo -e "\n${YELLOW}=== Testing Health Checks ===${NC}"

echo -e "\n${YELLOW}Testing FFmpeg health check...${NC}"
if docker run --rm --health-cmd="ffmpeg -version" ffmpeg-utility:6.1 sh -c "sleep 2; ffmpeg -version" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ FFmpeg health check works${NC}"
    ((passed++))
else
    echo -e "${RED}✗ FFmpeg health check failed${NC}"
    ((failed++))
fi

echo -e "\n${YELLOW}Testing ClamAV health check...${NC}"
if docker run --rm --health-cmd="clamscan --version" clamav-utility:1.3 sh -c "sleep 2; clamscan --version" >/dev/null 2>&1; then
    echo -e "${GREEN}✓ ClamAV health check works${NC}"
    ((passed++))
else
    echo -e "${RED}✗ ClamAV health check failed${NC}"
    ((failed++))
fi

# Summary
echo -e "\n=========================================="
echo -e "${YELLOW}Test Summary${NC}"
echo -e "=========================================="
echo -e "${GREEN}Passed: ${passed}${NC}"
echo -e "${RED}Failed: ${failed}${NC}"

if [ $failed -eq 0 ]; then
    echo -e "\n${GREEN}🎉 All tests passed! Utility images are ready for production.${NC}"
    exit 0
else
    echo -e "\n${RED}❌ Some tests failed. Please check the output above.${NC}"
    exit 1
fi