# PostgreSQL MCP Server – Troubleshooting (Cursor / Claude)

## Why it was failing on Windows

- **uvx.cmd breaks stdio**: Cursor spawns MCP servers over stdio. On Windows, `uvx` often resolves to `uvx.cmd`. That batch wrapper breaks the stdin/stdout handshake, so the Postgres MCP never starts correctly.
- **PATH**: Cursor may not see the same PATH as your terminal, so `uv` or `uvx` might not be found at all (`ENOENT`).

## What we changed

In `.mcp.json`, the Postgres MCP is configured to:

1. Call **`uv.exe` by full path** (e.g. `C:\Users\<You>\.local\bin\uv.exe`) so Cursor doesn’t rely on PATH.
2. Use **`uv tool run postgres-mcp`** (not `uv run`) so the tool is installed and run without the `uvx.cmd` wrapper.

## What you must set

1. **Real password in `DATABASE_URI`**  
   In `.mcp.json`, replace `YOUR_PASSWORD` in:

   ```text
   "DATABASE_URI": "postgresql://postgres:YOUR_PASSWORD@localhost:5432/dmis"
   ```

   Use your actual Postgres password. `.mcp.json` is gitignored, so it won’t be committed.

   **If your password contains special characters** (e.g. `!`, `@`, `#`, `%`), percent-encode them in the URL: `!` → `%21`, `@` → `%40`, `#` → `%23`, `%` → `%25`. Otherwise the connection string can be parsed incorrectly and auth will fail.

2. **Correct path to `uv.exe`**  
   If `uv` is installed somewhere other than `%USERPROFILE%\.local\bin\uv.exe`, update the `"command"` in `.mcp.json` to that path. In PowerShell:

   ```powershell
   (Get-Command uv).Source
   ```

   Use that path (with backslashes escaped as `\\` in JSON).

## After editing

- Restart Cursor (or use “Reload MCP” / “Restart MCP” if available) so it picks up the new config.
- Ensure PostgreSQL is running and that `postgres` can log in with the password you put in `DATABASE_URI`.

## If it still fails

- Check Cursor’s MCP logs for the exact error (e.g. connection refused, auth failed, or spawn error).
- Confirm `uv tool run postgres-mcp --access-mode=unrestricted` works in a normal terminal with the same `DATABASE_URI` in the environment.
