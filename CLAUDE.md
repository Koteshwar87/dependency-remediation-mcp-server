# CLAUDE.md

Guidance for Claude Code (and any AI assistant) working in this repository.

## What this project is

A **vulnerable dependency remediation tool** for Spring Boot Maven apps. It reads a
security team's vulnerability advisory (Excel export), scopes it to one app's fixable
Java library findings, applies the recommended version upgrades to `pom.xml`, and
confirms `mvn clean install` still passes.

The full, authoritative design lives in
[`docs/dependency-remediation-tool-plan_1.md`](docs/dependency-remediation-tool-plan_1.md).
**Read it before making non-trivial changes** — it defines scope, non-goals, the data
model, the dedupe rule, and the Phase 2 roadmap. If a change conflicts with the plan,
flag it rather than silently diverging.

## Core principles (do not violate)

1. **Deterministic core, LLM optional.** Parsing, filtering, dedupe, and version
   comparison are pure Python with no LLM calls. The LLM is only an *enhancement* for
   hard cases (unusual poms, build-failure recovery). The tool must work end-to-end
   with no model. Never move deterministic logic into an LLM prompt.
2. **Never claim success on a broken build.** A run is only "done" when
   `mvn clean install` is green. This rule is invariant across all phases.
3. **Edits other teams' code → must be auditable.** Dry-run by default; emit
   skipped-row, conflict, and change logs. Surface anything the engine can't safely
   change as a "needs manual review" item rather than guessing.
4. **Version comparison is Maven-aware, never string-based.** Use `version_compare`,
   not `str` sorting or `tuple(int, ...)`. Qualifiers like `.Final` / `-RC1` matter.
5. **MCP is the distribution layer, the engine is the product.** Keep `core/` free of
   adapter concerns; CLI and MCP are thin wrappers over the same functions.

## Scope guardrails (v1)

In scope: Spring Boot **Maven**, **Java library** findings, up to a green build —
**including BOM/parent-managed and purely-transitive findings**, remediated via a
`<dependencyManagement>` version pin (default strategy) and verified with
`mvn dependency:tree`. See plan §3 and §7 for the resolution-class classifier
(direct / property / managed / transitive / bom-coverable / ambiguous).

Out of scope (do not implement without being asked): Mend/portal APIs, container/OS
package fixes, Gradle, automated PRs, `<exclusions>`-based surgery, and auto-applying
BOM/parent upgrades (v1 only *suggests* those → manual-review bucket). These are Phase 2 —
see section 13 of the plan.

## Layout

Standard `src/` package (`src/dep_remediation/`). `core/` is the deterministic engine;
`cli.py` and `mcp_server.py` are thin adapters. Console entry points are defined in
`pyproject.toml`.

| Module | Phase | Purpose |
|--------|-------|---------|
| `core/advisory_parser.py` | 1 ✅ | Read Excel, apply filter chain, extract fields, dedupe → `Report` |
| `core/version_compare.py` | 2 ✅ | Maven-aware `compare()` / `version_key` / `max_version()` |
| `core/pom_fixer.py` | 3 ⬜ | Apply version upgrades to `pom.xml` (direct / property / parent / BOM) |
| `core/build_runner.py` | 4 ⬜ | Run `mvn clean install`, interpret result, gate on green |
| `cli.py` | ✅ | `dep-remediation` entry point — argparse over `core/` |
| `mcp_server.py` | 5 (partial ✅) | `dep-remediation-mcp` FastMCP server; `parse_advisory` tool live |

`core/advisory_parser.py` imports `core/version_compare.py` via a **relative** import
(`from .version_compare import version_key`). Core modules are import-only (no argparse
`main`); run via the entry points or `python -m dep_remediation.cli`.

## Data model

The advisory is a single-tab workbook. The engine reads clean columns only — no prose
parsing for the fix. Column names are centralized as `COL_*` constants in
`core/advisory_parser.py`; a sheet rename should be a one-line change there.

- Filter chain: `owner` == app, `Code Library Language` == `Java`,
  `Base image vulnerability` == `FALSE`.
- Extract: `DetailedName` (groupId:artifactId), `Version`, `RecommendedVersion`.
- Dedupe key: `DetailedName`; conflict resolution: **highest `RecommendedVersion`
  wins**, compared Maven-aware; log every conflict.
- `RecommendedVersion` is authoritative over `FixedVersion` (log divergence). If
  `DetailedName` is blank, fall back to coordinates from `Description` backticks.

## Commands

```bash
uv sync                       # or: pip install -e ".[dev]"

# Parse an advisory for an app  (or: python -m dep_remediation.cli ...)
dep-remediation tests/fixtures/dummy_advisory.xlsx --app app-alpha [--json] [--no-base-image-filter]

# Version-comparison self-tests
python -m dep_remediation.core.version_compare

# Run the MCP server (stdio; normally launched by an MCP client)
dep-remediation-mcp
```

`tests/fixtures/dummy_advisory.xlsx` is the local sample fixture (app `app-alpha`).

## Conventions

- Python 3.11+; `src/` layout, `pyproject.toml` is the dependency source of truth.
  Engine deps: `pandas`/`openpyxl`; MCP adapter: `mcp[cli]` (FastMCP).
- Keep modules deterministic and unit-testable; prefer pure functions returning
  dataclasses (`Finding`, `Conflict`, `Report`) over side effects.
- **MCP/stdio: never `print()` to stdout** — stdout carries JSON-RPC. Log to stderr
  (Python `logging`). This applies to `mcp_server.py` and anything it imports at runtime.
- When adding a new pom-structure case or version edge case, add a fixture/test for it.
- Don't introduce a network call into `core/`. Sources (Excel today, Mend later) belong
  behind a pluggable source interface (Phase 2.1).
