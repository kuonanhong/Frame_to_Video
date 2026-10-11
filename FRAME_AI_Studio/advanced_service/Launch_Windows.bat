@echo off
setlocal
if exist "%~dp0..\.venv-native\Scripts\python.exe" (
  "%~dp0..\.venv-native\Scripts\python.exe" "%~dp0server.py" %*
) else (
  py -3 "%~dp0server.py" %*
)
pause
