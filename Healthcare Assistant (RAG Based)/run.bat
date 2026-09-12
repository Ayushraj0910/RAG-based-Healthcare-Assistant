@echo off
REM One-command launcher: starts the backend, starts the frontend, opens the app.
REM Usage: run.bat   (run from the project root, the folder containing backend\ and frontend\)

setlocal
set BACKEND_PORT=8000
set FRONTEND_PORT=5500
set ROOT_DIR=%~dp0

echo Starting backend on port %BACKEND_PORT%...
cd /d "%ROOT_DIR%backend"

if not exist ".venv" (
  echo Creating virtual environment...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt

start "Healthcare Backend" cmd /k uvicorn main:app --port %BACKEND_PORT%

echo Starting frontend on port %FRONTEND_PORT%...
cd /d "%ROOT_DIR%frontend"
start "Healthcare Frontend" cmd /k python -m http.server %FRONTEND_PORT%

echo Waiting for backend to be ready...
timeout /t 5 /nobreak > nul

echo Opening http://localhost:%FRONTEND_PORT%
start http://localhost:%FRONTEND_PORT%

echo.
echo Healthcare Assistant is running:
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo Close the two opened terminal windows to stop the servers.
