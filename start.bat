@echo off
echo ============================================
echo   LeadPilot - Starting System...
echo ============================================
echo.

:: Activate virtual environment
call venv\Scripts\activate.bat 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Virtual environment not found. Run install.bat first!
    pause
    exit /b 1
)

:: Start Ollama in background (if not already running)
echo [1/3] Starting Ollama...
tasklist /FI "IMAGENAME eq ollama.exe" 2>NUL | find /I /N "ollama.exe" >nul
if %errorlevel% neq 0 (
    start /min "Ollama" ollama serve
    timeout /t 3 /nobreak >nul
    echo [OK] Ollama started
) else (
    echo [OK] Ollama already running
)

:: Start FastAPI server
echo [2/3] Starting LeadPilot server...
echo [INFO] Dashboard: http://localhost:8000
echo [INFO] API Docs:  http://localhost:8000/docs
echo [INFO] Press Ctrl+C to stop
echo.

:: Open browser after short delay
start /min cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

:: Run server (stays in foreground)
cd backend
python main.py
