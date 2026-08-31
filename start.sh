#!/usr/bin/env bash
# Stellaris Save Editor - Cross-Platform Startup Script
# Usage: ./start.sh or bash start.sh
set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}================================${NC}"
echo -e "${CYAN}  Stellaris Save Editor - Starting...${NC}"
echo -e "${CYAN}================================${NC}"

# 1. Check Python
echo -e "${YELLOW}[1/3] Checking Python...${NC}"
if command -v python3 &> /dev/null; then
    PYVER=$(python3 --version 2>&1)
    echo -e "  ${GREEN}OK: $PYVER${NC}"
elif command -v uv &> /dev/null; then
    echo -e "  ${YELLOW}python3 not found, trying uv...${NC}"
    uv run python --version
    echo -e "  ${GREEN}OK: using uv python${NC}"
else
    echo -e "  ${RED}ERROR: python3 not found. Install Python 3.10+${NC}"
    exit 1
fi

# 2. Install Node.js deps
echo -e "${YELLOW}[2/3] Installing Node.js dependencies...${NC}"
cd "$PROJECT_ROOT"
if command -v pnpm &> /dev/null; then
    pnpm install --frozen-lockfile 2>/dev/null
    echo -e "  ${GREEN}OK: pnpm install${NC}"
elif command -v bun &> /dev/null; then
    bun install --frozen-lockfile 2>/dev/null
    echo -e "  ${GREEN}OK: bun install${NC}"
else
    npm install 2>/dev/null
    echo -e "  ${GREEN}OK: npm install${NC}"
fi

# 3. Start Python service
echo -e "${YELLOW}[3/3] Starting Python save parser...${NC}"
fuser -k 3001/tcp 2>/dev/null || true
sleep 1
cd "$PROJECT_ROOT/mini-services/save-parser"
PORT=3001 python3 -u server.py &
PY_PID=$!
echo -e "  ${GREEN}Python service started (PID: $PY_PID) on :3001${NC}"

sleep 2
if curl -s http://localhost:3001/api/status > /dev/null 2>&1; then
    echo -e "  ${GREEN}Python service verified${NC}"
else
    echo -e "  ${YELLOW}WARNING: Python service may not have started${NC}"
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  Ready!${NC}"
echo -e "${GREEN}================================${NC}"
echo ""
echo -e "  Next.js:     ${CYAN}http://localhost:3000${NC}"
echo -e "  Py Service:  ${CYAN}http://localhost:3001${NC}"
echo ""
echo -e "${YELLOW}Press Ctrl+C to stop.${NC}"

# Cleanup
trap "echo -e '\n${YELLOW}Shutting down...${NC}'; kill $PY_PID 2>/dev/null; echo -e '  Python service stopped'" EXIT
wait