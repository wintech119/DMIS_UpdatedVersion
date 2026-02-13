@echo off
REM Avoid "Unable to move the cache: Access is denied" (OneDrive/sync lock).
REM Use C:\ so cache is never inside OneDrive; run from C:\ so cwd isn't synced.
set "ELECTRON_USER_DATA=C:\ClaudeCodeCache"
cd /d C:\
claude %*
