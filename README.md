# Vulnerable Dependency Remediation Tool

An LLM-agnostic tool that takes a security team's vulnerability advisory (an Excel
export), scopes it to one Spring Boot Maven application's **fixable Java library**
findings, applies the recommended version upgrades to the project's `pom.xml`, and
confirms the project still builds — without a developer hand-hunting through thousands
of rows.

The product ships as an **MCP (Model Context Protocol) server** wrapped over a
deterministic Python engine, so it imports into VS Code and IntelliJ AI assistants and
works with the developer's model of choice. A plain CLI over the same engine is provided
as a zero-LLM fallback.

> Full design and roadmap: [`docs/dependency-remediation-tool-plan_1.md`](docs/dependency-remediation-tool-plan_1.md)

---

## Why this exists

Dependabot, Renovate, Mend's native PRs, and OWASP Dependency-Check all scan against
public CVE feeds. The gap this tool fills: it is driven by the **security team's own
curated advisory export** as the source of truth, scoped to a single app's Java
libraries, applied through one LLM-agnostic interface that runs in any team's IDE.

## Scope (v1)

v1 covers **Spring Boot Maven** apps and stops at a **green build**. Raising a PR,
Mend API integration, and LLM-assisted build recovery are Phase 2 (see the plan).

Transitive / BOM-managed Java findings **are** in scope: they're remediated via a
`<dependencyManagement>` version pin, verified with `mvn dependency:tree` (this matters
because the advisory scans the resolved artifact, so most findings are managed/transitive,
not hand-pinned `<version>` tags).

**Non-goals (v1):** no Mend/portal connection, no container/OS package remediation,
no Gradle, no automated PRs. Also deferred: `<exclusions>`-based surgery and auto-applying
BOM/parent upgrades (those are *suggested* for manual review). See the plan for the exact
boundary.

---

## How it works

```
advisory.xlsx ──► filter (owner + Java + not base-image)
              ──► extract (DetailedName, Version, RecommendedVersion)
              ──► dedupe (highest RecommendedVersion wins, Maven-aware)
              ──► classify resolution (direct / property / managed / transitive)
              ──► apply to pom.xml: edit <version>/property, or add a
                  <dependencyManagement> pin for managed/transitive (dry-run by default)
              ──► mvn clean install (green) + mvn dependency:tree (resolved version check)
```

### Architecture

Standard `src/` package layout. The deterministic engine (`core/`) is the product;
the CLI and MCP server are thin adapters over it.

```
src/dep_remediation/
├── core/                       # LLM-agnostic engine (the real product)
│   ├── advisory_parser.py      # read Excel, filter, extract, dedupe -> normalized list   [Phase 1 ✅]
│   ├── version_compare.py      # Maven-aware version comparison                            [Phase 2 ✅]
│   ├── pom_fixer.py            # apply version upgrades to pom.xml                          [Phase 3 ⬜]
│   └── build_runner.py         # run mvn clean install, interpret result                   [Phase 4 ⬜]
├── cli.py                      # plain CLI adapter — works with no LLM                      [✅]
└── mcp_server.py               # FastMCP server exposing core/ as MCP tools                 [Phase 5 — parse tool ✅]
```

Entry points (from `pyproject.toml`): `dep-remediation` (CLI) and
`dep-remediation-mcp` (MCP stdio server). See [CLAUDE.md](CLAUDE.md).

---

## Getting started

`pyproject.toml` is the single source of truth for dependencies — works with either
[uv](https://docs.astral.sh/uv/) (recommended) or plain pip.

```bash
# uv
uv sync

# or pip
python -m venv .venv
.venv\Scripts\activate          # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev]"
```

### Parse an advisory (Phase 1)

```bash
# Human-readable summary  (console script, or: python -m dep_remediation.cli ...)
dep-remediation tests/fixtures/dummy_advisory.xlsx --app app-alpha

# Machine-readable output
dep-remediation tests/fixtures/dummy_advisory.xlsx --app app-alpha --json
```

Example output:

```
App: app-alpha
  Rows in sheet:           10
  Rows for this app:       9
  Java library rows:       7
  Skipped (other owner):   1
  Skipped (container/OS):  2
  Skipped (base image):    1

Unique libraries to fix: 4
  com.fasterxml.jackson.core:jackson-databind   2.13.0        -> 2.15.4
  io.netty:netty-codec-dns                      4.2.4.Final   -> 4.2.13.Final
  io.netty:netty-handler                        4.2.4.Final   -> 4.2.15.Final
  org.springframework:spring-core               5.3.32        -> 6.2.11

Conflicts resolved (highest version wins): 1
  io.netty:netty-handler: chose 4.2.15.Final  from ['4.2.13.Final', '4.2.15.Final']
```

### Verify version comparison (Phase 2)

```bash
python -m dep_remediation.core.version_compare   # runs the built-in self-tests
```

### Run as an MCP server (Phase 5 — `parse_advisory` tool)

The server speaks MCP over **stdio**, so an MCP client (VS Code / IntelliJ AI assistant,
Claude Desktop, etc.) launches it. Run directly:

```bash
dep-remediation-mcp           # or: uv run dep-remediation-mcp
```

Example client config (`mcpServers` entry):

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

It exposes one tool today — `parse_advisory(xlsx_path, app, base_image_filter=True)` —
returning the deduped fix list; `apply_fixes` (Phase 3) and `verify_build` (Phase 4)
follow. (stdio transport reserves stdout for JSON-RPC; the server logs to stderr.)

---

## The advisory sheet

A single-tab workbook. The engine reads clean columns only — **no prose parsing
required** for the fix:

| Field | Column | Example |
|-------|--------|---------|
| App / owner | `owner` | `app-alpha` |
| Language filter | `Code Library Language` | `Java` (blank = container/OS, dropped) |
| Base-image cross-check | `Base image vulnerability` | `FALSE` |
| Library identity | `DetailedName` | `org.springframework:spring-core` |
| Current version | `Version` | `5.3.32` |
| Version to apply | `RecommendedVersion` | `6.2.11` |

`Description` carries the same facts as templated prose and is used only as a fallback
for coordinates when `DetailedName` is blank.

---

## Trust & transparency

Because the tool edits other teams' code it is auditable by design:

- **Dry-run by default** — show the diff, apply on confirmation.
- **Skipped-rows log** — how many rows dropped and why.
- **Conflict log** — which duplicate versions were seen and which won.
- **Build gating** — success is never claimed on a broken build.

## Roadmap (Phase 2)

Automated PR creation → LLM-assisted build recovery → Mend API source → broader pom
coverage → CI/scale. The deterministic `core/` engine and the "never claim success on a
broken build" rule are invariant. See section 13 of the plan.
