$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
& ".\.venv\Scripts\streamlit.exe" run simulator\app.py @args
