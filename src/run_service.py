import os
import logging

import uvicorn
from dotenv import load_dotenv

load_dotenv()

# Configure logging with environment variable control and validation
log_level = os.getenv("LOG_LEVEL", "INFO").upper()

# Validate log level
valid_levels = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']
if log_level not in valid_levels:
    print(f"⚠️  Warning: Invalid LOG_LEVEL '{log_level}'. Using INFO instead.")
    print(f"Valid levels: {', '.join(valid_levels)}")
    log_level = 'INFO'

logging.basicConfig(
    level=getattr(logging, log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Log the current configuration for confirmation
logging.info(f"🚀 Opey II Service starting")
logging.info(f"📊 Log level: {log_level}")

if log_level == 'DEBUG':
    logging.info("🔍 DEBUG logging enabled - detailed OBP consent logging active")
    logging.info("💡 You'll see DEBUG messages for JWT analysis, headers, and API requests")

if __name__ == "__main__":
    if os.getenv("MODE") == "dev":
        logging.info("🛠️  Running in development mode with auto-reload")
        uvicorn.run("service:app", reload=True, log_level="info", port=int(os.getenv("PORT", 5000)))
    else:
        logging.info("🏭 Running in production mode")
        from service import app
        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
