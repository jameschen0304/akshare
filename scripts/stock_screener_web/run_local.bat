@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Installing deps if needed...
pip install fastapi uvicorn pandas akshare -q
echo.
echo Open http://127.0.0.1:8765 in your browser
python app.py
pause
