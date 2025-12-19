#!/usr/bin/env python3

"""
Entry point for the Flask application for the GitHub Actions Runners manager.
This script initializes the app and runs it, listening on the specified PORT.
"""

import os
from dotenv import load_dotenv
from app import create_app

load_dotenv()

app = create_app()

if __name__ == "__main__":
    # Never run with debug=True in production
    app.run(
        host='127.0.0.1',
        port=int(os.environ.get('PORT', 8080)),
        debug=False
    )
