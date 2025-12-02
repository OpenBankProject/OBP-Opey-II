#!/bin/bash
# Helper script to run Opey II with debug logging enabled

# Set the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "🔍 Starting Opey II with DEBUG logging enabled"
echo "📁 Project directory: $PROJECT_DIR"

# Export LOG_LEVEL as DEBUG
export LOG_LEVEL=DEBUG

# Change to project directory
cd "$PROJECT_DIR"

# Check if we're in development mode
if [ "$MODE" = "dev" ]; then
    echo "🛠️  Development mode detected"
    export MODE=dev
else
    echo "🏭 Production mode"
fi

# Run the service
echo "🚀 Starting service with DEBUG logging..."
echo "💡 You'll see detailed OBP consent information in the logs"
echo "🛑 Press Ctrl+C to stop"
echo ""

cd src && python run_service.py
