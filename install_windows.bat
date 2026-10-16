@echo off
chcp 65001 >nul
cd /d "%~dp0"
py -m venv .venv
call .venv\Scripts\activate
pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo ההתקנה הסתיימה. פתח את הקובץ .env והדבק בו את הטוקן של הבוט.
pause
