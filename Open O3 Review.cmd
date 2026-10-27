@echo off
cd /d "%~dp0"
set "O3_REVIEW_PYTHON=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%O3_REVIEW_PYTHON%" (
  echo This review needs the existing Python 3.12 runtime used for O3 verification.
  echo No files or settings have been changed. See READ_ME_FIRST.txt for details.
  pause
  exit /b 1
)
start "O3 Upgrade Review" "%O3_REVIEW_PYTHON%" -I -B "%~dp0review_app.py" --example
