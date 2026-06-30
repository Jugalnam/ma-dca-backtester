$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot
& ".\.venv\Scripts\python.exe" -m simulator.main @args
