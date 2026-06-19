#!/usr/bin/env bash

# Coiner startup script for Linux/macOS
# Starts the FastAPI backend and Vue frontend, then opens the browser

set -euo pipefail

echo "========================================"
echo "  Coiner Startup Script"
echo "========================================"

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VUE_DIR="${PROJECT_DIR}/vue-frontend"
VUE_DIST="${VUE_DIR}/dist"

# Detect OS for opening browser
open_browser() {
    local url="$1"
    if command -v xdg-open &>/dev/null; then
        xdg-open "$url" &>/dev/null
    elif command -v open &>/dev/null; then
        open "$url" &>/dev/null
    else
        echo "[INFO] Please open your browser manually: $url"
    fi
}

# Clean up on exit
cleanup() {
    echo ""
    echo "[INFO] Stopping services..."
    if [[ -n "${BACKEND_PID:-}" ]]; then
        kill "$BACKEND_PID" 2>/dev/null || true
        wait "$BACKEND_PID" 2>/dev/null || true
    fi
    if [[ -n "${FRONTEND_PID:-}" ]]; then
        kill "$FRONTEND_PID" 2>/dev/null || true
        wait "$FRONTEND_PID" 2>/dev/null || true
    fi
    echo "[INFO] Done."
}
trap cleanup INT TERM EXIT

# Build frontend
echo "[INFO] Building Vue frontend..."
if [[ -d "$VUE_DIST" ]]; then
    rm -rf "$VUE_DIST"
fi
cd "$VUE_DIR"
npm run build
cd "$PROJECT_DIR"

# Start backend
echo "[INFO] Starting backend (FastAPI) on port 8000..."
cd "$PROJECT_DIR"
python main.py &
BACKEND_PID=$!

# Wait for backend to start
echo "[INFO] Waiting for backend to start..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/ping >/dev/null 2>&1; then
        echo "[INFO] Backend is ready!"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:8000/api/ping >/dev/null 2>&1; then
    echo "[ERROR] Backend failed to start. Check logs above."
    exit 1
fi

# Start frontend dev server
echo "[INFO] Starting frontend dev server on port 3000..."
cd "$VUE_DIR"
npm run dev &
FRONTEND_PID=$!

# Wait for frontend to start
echo "[INFO] Waiting for frontend to start..."
for i in {1..30}; do
    if curl -s http://localhost:3000 >/dev/null 2>&1; then
        echo "[INFO] Frontend is ready!"
        break
    fi
    sleep 1
done

if ! curl -s http://localhost:3000 >/dev/null 2>&1; then
    echo "[ERROR] Frontend failed to start. Check logs above."
    exit 1
fi

# Open browser
echo ""
echo "========================================"
echo "  Coiner is running!"
echo "========================================"
echo ""
echo "  Backend:  http://localhost:8000"
echo "  Frontend: http://localhost:3000"
echo "  API Docs: http://localhost:8000/docs"
echo ""
echo "  Press Ctrl+C to stop"
echo ""

open_browser "http://localhost:3000"

# Wait for Ctrl+C
wait
