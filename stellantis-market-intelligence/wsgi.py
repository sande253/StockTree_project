"""Production WSGI entry point for Stellantis Market Intelligence.

Run with gunicorn:
    gunicorn --config gunicorn.conf.py wsgi:application

Or with waitress (Windows-friendly):
    waitress-serve --host=0.0.0.0 --port=8000 wsgi:application
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from api.main import create_app

# Configure logging before creating app
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('logs/app.log', mode='a')
    ]
)

# Create application instance
application = create_app()

if __name__ == "__main__":
    # For development only
    application.run(host='0.0.0.0', port=5000, debug=False)
