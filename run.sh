#!/usr/bin/env sh
set -e

echo "DEBUG: All environment variables:"
env | sort
echo "DEBUG: SUPERVISOR_TOKEN present: $([ -n "$SUPERVISOR_TOKEN" ] && echo YES || echo NO)"

exec python3 /app/main.py
