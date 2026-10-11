@echo off
rem First run installs packages and explicitly downloads SD-Turbo (several GB).
py -3.11 "%~dp0setup_native.py" --model sd-turbo --launch %*
if errorlevel 1 pause
