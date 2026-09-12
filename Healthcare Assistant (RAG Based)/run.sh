#!/usr/bin/env bash
# One-command launcher: starts the backend, starts the frontend, opens the app.
# Usage: ./run.sh   (run from the project root, the folder containing backend/ and frontend/)

set -e

BACKEND_PORT=8000
FRONTEND_PORT=5500
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
  echo ""
  echo "Stopping servers..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  exit 0
}
trap cleanup INT TERM

# --- Backend ---
echo "Starting backend on port $BACKEND_PORT..."
cd "$ROOT_DIR/backend"

if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt

uvicorn main:app --port "$BACKEND_PORT" &
BACKEND_PID=$!

# --- Frontend ---
echo "Starting frontend on port $FRONTEND_PORT..."
cd "$ROOT_DIR/frontend"
python3 -m http.server "$FRONTEND_PORT" > /dev/null 2>&1 &
FRONTEND_PID=$!

# --- Wait for backend to be ready, then open the browser ---
echo "Waiting for backend to be ready..."
for i in $(seq 1 30); do
  if curl -s "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
    break
  fi
  sleep 1
done

URL="http://localhost:$FRONTEND_PORT"
echo "Opening $URL"
if command -v open > /dev/null; then
  open "$URL"                 # macOS
elif command -v xdg-open > /dev/null; then
  xdg-open "$URL"              # Linux
else
  echo "Please open $URL manually in your browser."
fi

echo ""
echo "Healthcare Assistant is running:"
echo "  Backend:  http://localhost:$BACKEND_PORT"
echo "  Frontend: $URL"
echo "Press Ctrl+C to stop both servers."

wait
