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
│   ├── pom_fixer.py            # classify resolution + apply upgrades to pom.xml            [Phase 3 ✅]
│   └── build_runner.py         # mvn clean install + dependency:tree resolution check       [Phase 4 ✅]
├── cli.py                      # plain CLI adapter (parse / fix / verify subcommands)        [✅]
└── mcp_server.py               # FastMCP server (parse_advisory + apply_fixes + verify_build) [Phase 5 ✅]
```

Entry points (from `pyproject.toml`): `dep-remediation` (CLI) and
`dep-remediation-mcp` (MCP stdio server). See [CLAUDE.md](CLAUDE.md).

---

## Getting started

Requires **Python 3.11+** (and a Maven install — `mvn` on PATH or a project `mvnw`
wrapper — for the `verify` step). `pyproject.toml` is the single source of truth for
dependencies — works with either [uv](https://docs.astral.sh/uv/) (recommended) or plain pip.

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
dep-remediation parse tests/fixtures/dummy_advisory.xlsx --app app-alpha

# Machine-readable output
dep-remediation parse tests/fixtures/dummy_advisory.xlsx --app app-alpha --json
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
  Skipped (missing data):  0

Unique libraries to fix: 4
  LIBRARY                                          CURRENT        -> RECOMMENDED
  com.fasterxml.jackson.core:jackson-databind      2.13.0         -> 2.15.4
  io.netty:netty-codec-dns                         4.2.4.Final    -> 4.2.13.Final
  io.netty:netty-handler                           4.2.4.Final    -> 4.2.15.Final
  org.springframework:spring-core                  5.3.32         -> 6.2.11

Conflicts resolved (highest version wins): 1
  io.netty:netty-handler: chose 4.2.15.Final  from ['4.2.13.Final', '4.2.15.Final']
```

### Fix a pom (Phase 3)

Classifies how each flagged library resolves in the pom and applies the upgrade —
editing a direct `<version>`/property, or adding a `<dependencyManagement>` pin for
BOM-managed/transitive libraries. **Dry-run by default** (prints the diff); pass
`--apply` to write. Idempotent and never downgrades.

```bash
# Dry-run: show the resolution log + diff (add --json for machine-readable output)
dep-remediation fix path/to/pom.xml --from-advisory tests/fixtures/dummy_advisory.xlsx --app app-alpha

# Apply the changes
dep-remediation fix path/to/pom.xml --from-advisory tests/fixtures/dummy_advisory.xlsx --app app-alpha --apply
```

Each finding is reported with its resolution class and the strategy applied:

```
Actions: 4
  [transitive/add-pin]   com.fasterxml.jackson.core:jackson-databind: (managed/transitive) -> 2.15.4  (added <dependencyManagement> pin)
  [transitive/add-pin]   io.netty:netty-codec-dns: (managed/transitive) -> 4.2.13.Final  (added <dependencyManagement> pin)
  [direct/edit-version]  io.netty:netty-handler: 4.2.4.Final -> 4.2.15.Final
  [transitive/add-pin]   org.springframework:spring-core: (managed/transitive) -> 6.2.11  (added <dependencyManagement> pin)
```

followed by a unified diff — e.g. a parent-managed/transitive pom gets a pinned block:

```diff
+    <dependencyManagement>
+        <dependencies>
+            <!-- security pin -->
+            <dependency>
+                <groupId>io.netty</groupId>
+                <artifactId>netty-handler</artifactId>
+                <version>4.2.15.Final</version>
+            </dependency>
+        </dependencies>
+    </dependencyManagement>
```

### Verify the build (Phase 4)

Runs `mvn clean install` and gates on a **green build**, then runs `mvn dependency:tree`
to confirm each finding's *resolved* version is actually the recommended one (a pin can be
silently overridden by a BOM). Point it at the **aggregator root** for a multi-module
reactor — resolution is checked across every module.

```bash
# build-only gate
dep-remediation verify ./my-app

# build + resolved-version check against the advisory
dep-remediation verify ./my-app --from-advisory tests/fixtures/dummy_advisory.xlsx --app app-alpha

# fix and verify in one shot (only chains after a successful --apply)
dep-remediation fix ./my-app/pom.xml --from-advisory tests/fixtures/dummy_advisory.xlsx --app app-alpha --apply --verify
```

Overall success requires the build green **and** every finding resolved; unresolved
findings are surfaced for manual review. On failure the result carries the log tail, the
failing goal, and the just-applied bumps (likely culprits) so recovery can be driven
interactively. **Honest limit:** a green build proves the project *compiles*, not that a
forced transitive pin is runtime-safe.

### Run the tests

```bash
pytest -q
```

### Verify version comparison (Phase 2)

```bash
python -m dep_remediation.core.version_compare   # runs the built-in self-tests
```

### Run as an MCP server (Phase 5 — `parse_advisory` + `apply_fixes` + `verify_build`)

The server speaks MCP over **stdio**, so an MCP client (VS Code / IntelliJ AI assistant,
Claude Desktop, etc.) launches it. Run directly:

```bash
dep-remediation-mcp           # or: uv run dep-remediation-mcp
```

> **Full setup guide** (VS Code, IntelliJ, Claude Desktop configs + troubleshooting):
> [`docs/mcp-setup.md`](docs/mcp-setup.md). The protocol surface is covered by
> `tests/test_mcp_server.py` (an in-process MCP client round-trip).

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

Tools exposed today:
- `parse_advisory(xlsx_path, app, base_image_filter=True)` — the deduped fix list.
- `apply_fixes(pom_path, xlsx_path, app, apply=False)` — classify + apply upgrades to a
  pom; dry-run by default, returns the resolution log, manual-review bucket, and diff.
- `verify_build(project_dir, xlsx_path="", app="")` — `mvn clean install` + (optional)
  resolved-version check; returns the build result with actionable failure context.

(stdio transport reserves stdout for JSON-RPC; the server logs to stderr.)

### Try it end to end (example app)

[`examples/spring-boot-sample/`](examples/spring-boot-sample/) is a real, intentionally
**vulnerable** single-module Spring Boot app used as the end-to-end test bed — one seeded
finding per resolution class (direct / property / managed / transitive). A captured run of
parse → fix → green build + resolved-version check lives in
[`examples/spring-boot-sample/SHAKEOUT.md`](examples/spring-boot-sample/SHAKEOUT.md).

```bash
dep-remediation parse examples/spring-boot-sample/advisory.xlsx --app sample-app
# apply + verify on a COPY so the committed sample stays in its "before" state
```

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
- **Resolution log** — per finding: how it resolves (direct / property / managed /
  transitive) and the strategy applied (in-place edit vs. `<dependencyManagement>` pin),
  plus a manual-review bucket for anything not safely fixable.
- **Idempotent, no-downgrade** edits — re-running a fix is a no-op; an existing higher
  version is never lowered.
- **Build gating + resolved-version check** — success is never claimed on a broken build,
  and `mvn dependency:tree` must confirm each finding actually resolved to the recommended
  version (a pin silently overridden by a BOM is flagged, not hidden).

## Roadmap (Phase 2)

Automated PR creation → LLM-assisted build recovery → Mend API source → broader pom
coverage → CI/scale. The deterministic `core/` engine and the "never claim success on a
broken build" rule are invariant. See section 13 of the plan.
