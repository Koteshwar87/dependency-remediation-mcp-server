"""MCP server adapter — exposes the deterministic engine as MCP tools.

Built on the official MCP Python SDK (FastMCP). Imports into VS Code / IntelliJ AI
assistants and any MCP client; works with the developer's model of choice.

Transport is stdio: stdout carries JSON-RPC, so this module must NEVER print to
stdout. Use `logging` (configured to stderr) for diagnostics.

Entry point: `dep-remediation-mcp` (see pyproject [project.scripts]) or
`python -m dep_remediation.mcp_server`.

v1 exposes Phase-1 parsing and Phase-3 pom fixing; `verify_build` (Phase 4) follows.
"""
from __future__ import annotations
import logging

from mcp.server.fastmcp import FastMCP

from .core.advisory_parser import parse
from .core.pom_fixer import apply_fixes as _apply_fixes

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


@mcp.tool()
def apply_fixes(pom_path: str, xlsx_path: str, app: str, apply: bool = False) -> dict:
    """Apply an advisory's recommended Java upgrades to a Spring Boot pom.xml.

    Parses the advisory for `app`, then classifies how each library resolves in the pom
    (direct version / property / managed / transitive) and either edits the version in
    place or adds a <dependencyManagement> pin. Returns the resolution log (actions),
    the manual-review bucket, and a unified diff.

    Defaults to a DRY RUN (`apply=False`): nothing is written, the diff shows what would
    change. Set `apply=True` to write the pom. Idempotent and never downgrades.

    Args:
        pom_path: Path to the Spring Boot pom.xml to edit.
        xlsx_path: Path to the advisory .xlsx file.
        app: The owner/app name to filter by (matched case-insensitively).
        apply: Write changes to the pom when True; otherwise dry-run (default).
    """
    rep = parse(xlsx_path, app)
    return _apply_fixes(pom_path, rep.findings, dry_run=not apply).to_dict()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
