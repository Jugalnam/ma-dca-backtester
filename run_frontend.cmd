@echo off
setlocal
cd /d "%~dp0frontend"
set "PATH=C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin;C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\bin;%PATH%"
set "CI=true"
pnpm dev
