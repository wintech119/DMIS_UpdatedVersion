@echo off
cd /d "%~dp0..\backend"
".venv\Scripts\python.exe" run_mcp.py --settings dmis_api.settings --transport stdio
