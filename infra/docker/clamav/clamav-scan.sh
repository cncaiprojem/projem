#!/bin/sh
# ClamAV Scanner Script
set -e

# Check if virus database exists, if not download it
if [ ! -f /var/lib/clamav/main.cvd ] && [ ! -f /var/lib/clamav/main.cld ]; then
    echo "Downloading virus database..."
    freshclam --no-warnings || echo "Warning: Could not update database"
fi

# Run clamscan with provided arguments
exec clamscan "$@"