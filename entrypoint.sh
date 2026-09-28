#!/bin/sh
set -e

# Use PORT from environment or default to 8080
PORT=${PORT:-8080}
exec gunicorn --bind "0.0.0.0:${PORT}" --workers 2 --timeout 120 app:app