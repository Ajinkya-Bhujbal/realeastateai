@echo off
echo ============================================
echo   LeadPilot - AI Real Estate Lead Manager
echo   Installation Script
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.10+ from python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Create virtual environment
echo.
echo [1/4] Creating virtual environment...
if not exist "venv" (
    python -m venv venv
)
echo [OK] Virtual environment ready

:: Activate and install dependencies
echo.
echo [2/4] Installing Python dependencies (this may take a few minutes)...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [WARN] Some packages may have failed. Trying without version pins...
    pip install fastapi uvicorn sqlalchemy pydantic requests apscheduler chromadb sentence-transformers
)
echo [OK] Dependencies installed

:: Check Ollama
echo.
echo [3/4] Checking Ollama...
ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Ollama not found.
    echo        Download from: https://ollama.com/download/windows
    echo        After installing Ollama, run this script again.
    echo.
) else (
    echo [OK] Ollama found
    echo [INFO] Pulling Phi-3 Mini model (this may take a while on first run)...
    ollama pull phi3:mini
    echo [OK] Model ready
)

:: Create data directory
echo.
echo [4/4] Setting up data directory...
if not exist "data" mkdir data
echo [OK] Data directory ready

echo.
echo ============================================
echo   Installation Complete!
echo   Run start.bat to launch the system
echo ============================================
pause
