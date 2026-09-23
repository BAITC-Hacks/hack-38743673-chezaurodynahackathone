@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  start "" http://127.0.0.1:8000
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" run.py
  goto end
)
where py >nul 2>&1
if %errorlevel%==0 (
  start "" http://127.0.0.1:8000
  py -3 run.py
  goto end
)
where python >nul 2>&1
if %errorlevel%==0 (
  start "" http://127.0.0.1:8000
  python run.py
  goto end
)
echo Установите Python 3.11 или новее и запустите этот файл ещё раз.
:end
pause
