---
name: remediate-dependencies
description: Drive the vulnerable-dependency remediation workflow for a Spring Boot Maven app — parse a security advisory Excel, scope it to the app's fixable Java libraries, dedupe to one target version per library, then (Phase 3+) apply the upgrades to pom.xml and confirm mvn clean install is green. Use when the user wants to remediate vulnerable dependencies, process an advisory/Mend export, or bump dependency versions from a security report.
---

# Remediate dependencies

Workflow skill for this repo's dependency remediation tool. The engine is deterministic
and LLM-free; your job is to drive it, interpret its logs, and surface anything it can't
safely change. **Read `CLAUDE.md` and `dependency-remediation-tool-plan_1.md` first** if
you haven't this session.

## Inputs to gather

- **Advisory Excel** path (e.g. `tests/fixtures/dummy_advisory.xlsx`).
- **App / owner name** as it appears in the `owner` column (case-insensitive match).
- For the fix step: path to the target Spring Boot project's `pom.xml`.

If the app name or Excel path is missing and not obvious, ask before running.

## Steps

### 1. Parse + dedupe (Phase 1 — available now)

```bash
# console script (or: python -m dep_remediation.cli ...)
dep-remediation <advisory.xlsx> --app <owner> --json
```

The same logic is exposed over MCP as the `parse_advisory` tool by
`dep-remediation-mcp` — prefer that tool when driving the workflow from an MCP client.

Report back from the output:
- counts (total rows, rows for app, Java rows, skipped owner/lang/base-image/missing),
- the unique libraries to fix (`coordinate`, `current_version` → `recommended_version`),
- every conflict resolved (which candidate versions were seen, which won and why —
  highest `RecommendedVersion`, Maven-aware).

Do not hand-edit the dedupe result; if a chosen version looks wrong, check it with
`dep_remediation.core.version_compare.compare` rather than overriding by eye.

### 2. Apply to pom.xml (Phase 3 — `pom_fixer.py`, available now)

```bash
# dry-run (shows the diff; or: the apply_fixes MCP tool with apply=False)
dep-remediation fix <pom.xml> --from-advisory <advisory.xlsx> --app <owner>
# write the changes
dep-remediation fix <pom.xml> --from-advisory <advisory.xlsx> --app <owner> --apply
```

**Dry-run first**, show the diff, apply only on confirmation. The engine first
**classifies how each coordinate resolves**, then applies (static analysis, no Maven):

- `direct` (literal `<version>`) → edit in place
- `property` (`<properties>` entry) → edit the property value
- `managed` (parent / `spring-boot-starter-parent` / imported BOM) → **add/update a
  `<dependencyManagement>` pin** (the default strategy)
- `transitive` (not in the pom at all) → **add a `<dependencyManagement>` pin**
- `ambiguous` (unresolvable property) → **needs-manual-review** bucket — list it
  explicitly; never guess-edit.

Relay the resolution log (per finding: class → strategy) and the diff. The fixer is
idempotent and never downgrades (re-running on a fixed pom is a no-op). BOM/parent
upgrades are not auto-applied in v1.

### 3. Verify the build (Phase 4 — `build_runner.py`, available now)

```bash
# build + resolved-version check (or the verify_build MCP tool)
dep-remediation verify <project_dir> --from-advisory <advisory.xlsx> --app <owner>
# or fix + verify in one step
dep-remediation fix <pom.xml> --from-advisory <advisory.xlsx> --app <owner> --apply --verify
```

Point `verify` at the **aggregator root** for a multi-module reactor (resolution is
checked across all modules). **Never report success unless the build is green AND every
finding resolved to the recommended version** (`success` already encodes this; a pin can
be silently overridden by a BOM → surfaced as needs-manual-review). On failure, relay the
`log_tail`, `failing_goal`, and `attempted` culprits, then propose a fix and re-run
`apply_fixes`/`verify_build` (this is the interactive recovery loop — the automated one is
Phase 2). Honest limit: a green build proves it compiles, not that a forced transitive pin
is runtime-safe.

## Guardrails

- Stay in v1 scope: Spring Boot **Maven**, **Java** libs (including BOM-managed and
  transitive, via `<dependencyManagement>` pins), up to a green build. Mend API,
  container/OS packages, Gradle, automated PRs, `<exclusions>`-based surgery, and
  auto-applying BOM/parent upgrades are Phase 2 — don't implement them unless asked.
- Keep `core/` deterministic and network-free.
- Be transparent: always relay the skipped-rows log and conflict log, not just the final
  list — that auditability is the point of the tool.
