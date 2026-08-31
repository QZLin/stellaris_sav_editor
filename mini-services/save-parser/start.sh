#!/bin/bash
fuser -k 3001/tcp 2>/dev/null
sleep 1
cd "$(dirname "$0")"
exec python3 -u server.py
