# Avoid "Unable to move the cache: Access is denied" (OneDrive/sync lock).
# Use C:\ so cache is never inside OneDrive; run from C:\ so cwd isn't synced.
$env:ELECTRON_USER_DATA = "C:\ClaudeCodeCache"
Set-Location C:\
& claude @args
