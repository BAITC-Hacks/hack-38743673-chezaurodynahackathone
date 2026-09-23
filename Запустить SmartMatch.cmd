@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" (
  "%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" run.py --open-browser
  goto end
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -3 run.py --open-browser
  goto end
)
where python >nul 2>&1
if %errorlevel%==0 (
  python run.py --open-browser
  goto end
)
echo Установите Python 3.11 или новее и запустите этот файл ещё раз.
:end
pause
