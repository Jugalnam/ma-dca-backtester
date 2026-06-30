@echo off
setlocal
cd /d "%~dp0"
start "MA DCA API" "%ComSpec%" /k call "%~dp0run_api.cmd"
start "MA DCA Web" "%ComSpec%" /k call "%~dp0run_frontend.cmd"
