#!/usr/bin/env sh
set -e

exec s6-envdir /run/s6/container_environment python3 /app/main.py
