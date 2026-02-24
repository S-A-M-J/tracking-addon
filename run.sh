#!/usr/bin/env sh
set -e

# Load S6 container environment variables (includes SUPERVISOR_TOKEN)
if [ -d /run/s6/container_environment ]; then
    for env_file in /run/s6/container_environment/*; do
        export "$(basename "$env_file")=$(cat "$env_file")"
    done
fi

exec python3 /app/main.py
