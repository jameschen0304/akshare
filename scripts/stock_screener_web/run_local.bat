@echo off
chcp 65001 >nul
cd /d "%~dp0"
set HTTP_PROXY=
set HTTPS_PROXY=
set ALL_PROXY=
set NO_PROXY=*
echo Installing deps if needed...
pip install -r requirements-deploy.txt -q
echo.
echo Open http://127.0.0.1:8765 in your browser
echo Press Ctrl+C to stop.
python app.py
pause
