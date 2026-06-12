#!/bin/bash
# OCV Edit startup script
# Starts both the Python API server and the SvelteKit dev server

echo "=== OCV Edit ==="
echo ""

# Start Python API server in background
echo "Starting Python API server (port 8000)..."
cd "$(dirname "$0")"
uvicorn server.main:app --reload --host 0.0.0.0 --port 8000 &
API_PID=$!

# Start frontend dev server
echo "Starting SvelteKit dev server (port 5173)..."
cd frontend
npm run dev -- --open &
UI_PID=$!

echo ""
echo "API:  http://localhost:8000"
echo "UI:   http://localhost:5173"
echo "Docs: http://localhost:8000/docs"
echo ""
echo "Press Ctrl+C to stop both servers"

trap "kill $API_PID $UI_PID 2>/dev/null; exit" SIGINT SIGTERM
wait
