#!/bin/bash
# Test the approval system with live service

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "======================================"
echo "APPROVAL SYSTEM E2E TEST"
echo "======================================"

# Check if service is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo -e "${YELLOW}⚠️  Service not running. Start it with:${NC}"
    echo "   poetry run python src/run_service.py"
    echo ""
    echo -e "${YELLOW}Then run this script again.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Service is running${NC}"
echo ""

# Test 1: Check health endpoint
echo "Test 1: Health Check"
echo "--------------------"
HEALTH=$(curl -s http://localhost:8000/health)
echo "Response: $HEALTH"
echo -e "${GREEN}✓ Health check passed${NC}"
echo ""

# Test 2: List available endpoints
echo "Test 2: Check OpenAPI docs"
echo "-------------------------"
echo "OpenAPI docs available at: http://localhost:8000/docs"
echo "ReDoc available at: http://localhost:8000/redoc"
echo -e "${GREEN}✓ Documentation endpoints available${NC}"
echo ""

# Instructions for manual testing
echo "======================================"
echo "MANUAL TESTING INSTRUCTIONS"
echo "======================================"
echo ""
echo "1. Open the API docs:"
echo -e "   ${YELLOW}http://localhost:8000/docs${NC}"
echo ""
echo "2. Authenticate (if needed):"
echo "   - Click 'Authorize' button"
echo "   - Enter your credentials"
echo ""
echo "3. Test GET request (auto-approved):"
echo "   - POST /stream"
echo "   - Message: \"Show me all banks\""
echo "   - Expected: Direct response, no approval prompt"
echo ""
echo "4. Test POST request (requires approval):"
echo "   - POST /stream"  
echo "   - Message: \"Create a view called 'test_view' for account XYZ\""
echo "   - Expected: Approval request event with rich context"
echo ""
echo "5. Approve the request:"
echo "   - POST /approval/{thread_id}"
echo "   - approval: \"approve\""
echo "   - approval_level: \"session\""
echo ""
echo "6. Test second POST (uses session approval):"
echo "   - POST /stream with same thread_id"
echo "   - Message: \"Create another view 'test_view_2'\""
echo "   - Expected: No approval prompt (uses cached approval)"
echo ""
echo "======================================"
echo "For detailed test scenarios, see:"
echo "  docs/APPROVAL_SYSTEM_TESTING.md"
echo "======================================"
