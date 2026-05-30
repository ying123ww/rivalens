#!/usr/bin/env python3
"""
GPT-Researcher Backend Server Startup Script

Run this to start the research API server.
"""

import uvicorn
import os
import sys
from dotenv import load_dotenv

# Add the backend directory to Python path
backend_dir = os.path.dirname(os.path.abspath(__file__))
repo_root = os.path.abspath(os.path.join(backend_dir, ".."))
import os as _os
_os.environ.pop("OPENAI_API_KEY", None)
load_dotenv(os.path.join(repo_root, ".env"))
sys.path.insert(0, repo_root)
sys.path.insert(0, backend_dir)

if __name__ == "__main__":
    # Change to backend directory
    os.chdir(backend_dir)
    
    # Start the server
    uvicorn.run(
        "server.app:app",
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        log_level="info"
    )



