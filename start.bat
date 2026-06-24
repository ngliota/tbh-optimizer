@echo off
REM TBH Optimizer launcher — starts the localhost dashboard and opens the browser.
cd /d "%~dp0"

REM If the server is already up, just open the browser instead of starting a second one.
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/status -TimeoutSec 2) > $null; exit 0 } catch { exit 1 }"
if %errorlevel%==0 (
    echo TBH Optimizer already running. Opening browser...
    start "" "http://localhost:8000"
    exit /b 0
)

echo Starting TBH Optimizer on http://localhost:8000 ...
start "" /b ".venv\Scripts\python.exe" -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 --log-level warning

REM Wait for the server to answer, then open the browser.
powershell -NoProfile -Command "for ($i=0; $i -lt 30; $i++) { try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/status -TimeoutSec 1) > $null; break } catch { Start-Sleep -Milliseconds 500 } }"
start "" "http://localhost:8000"
