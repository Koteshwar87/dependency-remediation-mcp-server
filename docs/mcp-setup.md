# MCP server setup

How to install and connect the **dependency-remediation MCP server** to your IDE's AI
assistant. The server is LLM-agnostic — it works with whatever model your MCP client uses.

## Prerequisites

- **Python 3.11+**
- **Maven** — `mvn` on PATH, or a project `mvnw`/`mvnw.cmd` wrapper. Only needed for the
  `verify_build` tool; parsing and pom fixing work without it.
- The package installed (which provides the `dep-remediation-mcp` entry point):

```bash
# from the repo root — uv (recommended)
uv sync

# or pip
pip install -e .
```

Confirm the server starts (Ctrl-C to stop — it waits for a client on stdio):

```bash
dep-remediation-mcp
```

> The server speaks MCP over **stdio**: stdout carries JSON-RPC, logs go to stderr. Your
> MCP client launches the process; you normally don't run it by hand.

## Client configuration

Use an **absolute path** to the repo. Two launch styles work:

- `uv --directory <repo> run dep-remediation-mcp` (no activated venv needed), or
- the `dep-remediation-mcp` console script directly (must be on the client's PATH, e.g.
  the venv where you installed it).

### VS Code

`.vscode/mcp.json` in your workspace (or the `mcp.servers` block in user settings):

```json
{
  "servers": {
    "dep-remediation": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/TO/dependency-remediation-mcp-server", "run", "dep-remediation-mcp"]
    }
  }
}
```

### IntelliJ IDEA (AI Assistant)

Settings → Tools → AI Assistant → Model Context Protocol (MCP) → add a server:

- **Command:** `uv`
- **Arguments:** `--directory /ABSOLUTE/PATH/TO/dependency-remediation-mcp-server run dep-remediation-mcp`

(or set Command to the absolute path of `dep-remediation-mcp` with no arguments).

### Claude Desktop

`claude_desktop_config.json`
(macOS: `~/Library/Application Support/Claude/`, Windows: `%APPDATA%\Claude\`):

```json
{
  "mcpServers": {
    "dep-remediation": {
      "command": "uv",
      "args": ["--directory", "/ABSOLUTE/PATH/TO/dependency-remediation-mcp-server", "run", "dep-remediation-mcp"]
    }
  }
}
```

Restart the client after editing its config.

## Tools exposed

| Tool | Purpose | Notes |
|------|---------|-------|
| `parse_advisory(xlsx_path, app, base_image_filter=True)` | Deduped Java fix list for one app | read-only |
| `apply_fixes(pom_path, xlsx_path, app, apply=False)` | Classify + apply upgrades to a pom | **dry-run by default**; set `apply=True` to write |
| `verify_build(project_dir, xlsx_path="", app="")` | `mvn clean install` + resolved-version check | point at the aggregator root for a reactor; needs Maven |

Typical flow from the assistant: `parse_advisory` → `apply_fixes` (review the diff) →
`apply_fixes(apply=True)` → `verify_build`.

## Troubleshooting

- **Server exits immediately / "not connected":** the client must launch it; running
  `dep-remediation-mcp` in a terminal just waits on stdio. Check the client's MCP logs.
- **`dep-remediation-mcp: command not found`:** it isn't on the client's PATH — use the
  `uv --directory <repo> run …` form, or point `command` at the absolute path of the script
  in your venv (`.venv/Scripts/dep-remediation-mcp.exe` on Windows, `.venv/bin/...` else).
- **Garbled/again JSON-RPC errors:** something printed to **stdout**. Only JSON-RPC may go
  to stdout; all diagnostics must use stderr (the server already does this).
- **`verify_build` says "Maven not found":** install Maven or run from a project with a
  `mvnw` wrapper.
- **Relative paths fail:** always pass absolute paths for `xlsx_path`, `pom_path`, and
  `project_dir` — the server's working directory is set by the client, not you.

The protocol surface is covered by `tests/test_mcp_server.py` (in-process MCP client).
