import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    if os.getenv("MODE") != "dev":
        from service import app

        uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
    else:
        uvicorn.run("service:app", reload=True, log_level="debug", port=int(os.getenv("PORT", 5000)))