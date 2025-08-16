#!/bin/bash
# Start virtual display for headless operation
Xvfb :99 -screen 0 1024x768x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99
# Wait for X server to start
sleep 2
# Execute CAMotics with provided arguments
exec camotics "$@"