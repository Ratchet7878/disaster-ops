#!/usr/bin/env bash
# Serves the DisasterOps frontend on http://localhost:8080
# No build step, no npm install -- just a static file server.
set -e
cd "$(dirname "$0")"
echo "Starting DisasterOps frontend on http://localhost:8080 ..."
echo "(Make sure run_backend.sh is running in another terminal first.)"
python3 -m http.server 8080
