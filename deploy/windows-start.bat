@echo off
REM Windows quick start for KYGSMOTO
set ROOT=%~dp0..
cd /d %ROOT%

if not exist .venv (
  py -3 -m venv .venv
)
call .venv\Scripts\activate
pip install -r backend\requirements.txt

cd frontend
call npm ci
call npm run build
if not exist ..\backend\static mkdir ..\backend\static
xcopy /E /I /Y dist\* ..\backend\static\
cd ..

echo Starting KYGSMOTO on http://127.0.0.1:8000
uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000
