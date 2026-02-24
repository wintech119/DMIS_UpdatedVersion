@echo off
REM Avoid "Unable to move the cache: Access is denied" (OneDrive/sync lock).
REM Use a local cache path and run from the system drive root.
set "ELECTRON_USER_DATA=%LOCALAPPDATA%\ClaudeCodeCache"
cd /d "%SystemDrive%\"
claude %*
