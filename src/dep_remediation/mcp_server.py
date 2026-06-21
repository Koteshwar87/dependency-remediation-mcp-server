"""MCP server adapter — exposes the deterministic engine as MCP tools.

Built on the official MCP Python SDK (FastMCP). Imports into VS Code / IntelliJ AI
assistants and any MCP client; works with the developer's model of choice.

Transport is stdio: stdout carries JSON-RPC, so this module must NEVER print to
stdout. Use `logging` (configured to stderr) for diagnostics.

Entry point: `dep-remediation-mcp` (see pyproject [project.scripts]) or
`python -m dep_remediation.mcp_server`.

v1 exposes Phase-1 parsing; `apply_fixes` (Phase 3) and `verify_build` (Phase 4)
tools will be added as the engine grows.
"""
from __future__ import annotations
import logging

from mcp.server.fastmcp import FastMCP

from .core.advisory_parser import parse

logging.basicConfig(level=logging.INFO)  # logging defaults to stderr (stdout = JSON-RPC)

mcp = FastMCP("dep-remediation")


@mcp.tool()
def parse_advisory(xlsx_path: str, app: str, base_image_filter: bool = True) -> dict:
    """Parse a security advisory Excel and return the deduped Java fix list for one app.

    Filters the sheet to the app's fixable Java libraries, extracts each library's
    coordinate / current version / recommended version, and dedupes to one target
    version per library (highest RecommendedVersion wins, Maven-aware). Returns the
    normalized report including transparency counters and resolved conflicts.

    Args:
        xlsx_path: Path to the advisory .xlsx file.
        app: The owner/app name to filter by (matched case-insensitively).
        base_image_filter: Skip rows where Base image vulnerability = TRUE (default True).
    """
    return parse(xlsx_path, app, base_image_filter=base_image_filter).to_dict()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
