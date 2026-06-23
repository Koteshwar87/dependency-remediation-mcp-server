"""MCP server adapter — exposes the deterministic engine as MCP tools.

Built on the official MCP Python SDK (FastMCP). Imports into VS Code / IntelliJ AI
assistants and any MCP client; works with the developer's model of choice.

Transport is stdio: stdout carries JSON-RPC, so this module must NEVER print to
stdout. Use `logging` (configured to stderr) for diagnostics.

Entry point: `dep-remediation-mcp` (see pyproject [project.scripts]) or
`python -m dep_remediation.mcp_server`.

v1 exposes Phase-1 parsing, Phase-3 pom fixing, and Phase-4 build verification.
"""
from __future__ import annotations
import logging

from mcp.server.fastmcp import FastMCP

from .core.advisory_parser import parse, apply_overrides
from .core.pom_fixer import apply_fixes as _apply_fixes
from .core import build_runner

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
def apply_fixes(pom_path: str, xlsx_path: str, app: str, apply: bool = False,
                overrides: dict[str, str] | None = None) -> dict:
    """Apply an advisory's recommended Java upgrades to a Spring Boot pom.xml.

    Parses the advisory for `app`, then classifies how each library resolves in the pom
    (direct version / property / managed / transitive) and either edits the version in
    place or adds a <dependencyManagement> pin. Returns the resolution log (actions),
    the manual-review bucket, and a unified diff.

    Defaults to a DRY RUN (`apply=False`): nothing is written, the diff shows what would
    change. Set `apply=True` to write the pom. Idempotent and never downgrades.

    `overrides` curates the fix set for the build-failure recovery loop: map a coordinate
    to a replacement version to re-target it, or to "" to drop it (skip → manual-review).
    The engine does NOT revert prior edits, so re-apply against a clean copy of the pom.

    Args:
        pom_path: Path to the Spring Boot pom.xml to edit.
        xlsx_path: Path to the advisory .xlsx file.
        app: The owner/app name to filter by (matched case-insensitively).
        apply: Write changes to the pom when True; otherwise dry-run (default).
        overrides: Optional {coordinate: version} re-targets; "" drops that finding.
    """
    rep = parse(xlsx_path, app)
    findings = apply_overrides(rep.findings, overrides)
    return _apply_fixes(pom_path, findings, dry_run=not apply).to_dict()


@mcp.tool()
def verify_build(project_dir: str, xlsx_path: str = "", app: str = "") -> dict:
    """Build a Maven project and confirm the advisory fixes actually resolved.

    Runs `mvn clean install` (point `project_dir` at the aggregator root for a reactor) and
    gates on a green build. When `xlsx_path` and `app` are given, also runs
    `mvn dependency:tree` and checks every advisory finding resolved to its recommended
    version across all modules — `success` is True only if the build is green AND all
    findings resolved.

    On failure the result carries actionable context (`log_tail`, `failing_goal`,
    `attempted`) so recovery can be driven interactively. A green build proves the project
    compiles; it does not guarantee a forced transitive pin is runtime-safe.

    Args:
        project_dir: Path to the Maven project (aggregator root for a multi-module build).
        xlsx_path: Optional advisory .xlsx to enable the resolved-version check.
        app: Optional owner/app name to filter the advisory by (used with xlsx_path).
    """
    findings = ()
    if xlsx_path and app:
        findings = parse(xlsx_path, app).findings
    return build_runner.verify(project_dir, findings).to_dict()


def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
