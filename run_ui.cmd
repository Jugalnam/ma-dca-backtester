@echo off
setlocal
cd /d "%~dp0"
".\.venv\Scripts\streamlit.exe" run simulator\app.py %*
