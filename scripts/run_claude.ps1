# Avoid "Unable to move the cache: Access is denied" (OneDrive/sync lock).
# Use a local cache path and run from the system drive root.
$env:ELECTRON_USER_DATA = Join-Path $env:LOCALAPPDATA "ClaudeCodeCache"
Set-Location "$($env:SystemDrive)\"
& claude @args
