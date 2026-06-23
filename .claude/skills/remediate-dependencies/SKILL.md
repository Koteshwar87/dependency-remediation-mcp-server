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
dep-remediation fix <pom.xml-or-project-dir> --from-advisory <advisory.xlsx> --app <owner>
# write the changes
dep-remediation fix <pom.xml-or-project-dir> --from-advisory <advisory.xlsx> --app <owner> --apply
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

**Multi-module reactors are auto-targeted.** Point `fix` at the **project dir or aggregator
pom** and the engine routes each finding to the right pom by itself: direct/property findings
are edited in the module that declares them; managed/transitive findings are pinned once in
the aggregator (inherited by all modules). Do **not** hand-route with per-module commands —
the result lists per-pom actions under `poms`, each action tagged with its `pom_path`.

Relay the resolution log (per finding: class → strategy → which pom) and the diff. The fixer
is idempotent and never downgrades (re-running on a fixed pom is a no-op). BOM/parent
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
be silently overridden by a BOM → surfaced as needs-manual-review). Honest limit: a green
build proves it compiles, not that a forced transitive pin is runtime-safe.

### 4. Recovery loop when the build goes red (you drive this)

The engine reports *facts*; you make the *judgment* about what to retry. Run a **bounded**
loop (max ~3 attempts), always re-applying to a **fresh copy** of the project — the engine
does **not** revert prior edits, so each attempt must start from a clean baseline pom.

1. Apply the full fix set → `verify_build`. If green and all resolved → done.
2. If red, read the structured failure: `failure_kind`, `suspects`, and `attempted`
   (the bumps just applied — the likely culprits).
3. Decide, per `failure_kind`:
   - **`dependency_resolution`** (a recommended version can't be fetched — yanked / typo /
     wrong repo): drop each `suspect` → manual-review. v1 does **not** auto-discover a
     replacement; only re-target if the user/advisory gives a known-good version.
   - **`compilation`** / **`test`**: the failure rarely names a coordinate — correlate with
     `attempted` and drop the most likely culprit → manual-review (or re-target if you have
     a known-good version). Prefer dropping one at a time so you learn which bump broke it.
4. Re-apply the **curated** set to a fresh copy and `verify_build` again:
   - CLI: `dep-remediation fix <pom> --from-advisory <xlsx> --app <owner> --apply \`
     `  --skip <coord>` (drop) and/or `--override <coord>=<version>` (re-target), repeatable.
   - MCP: `apply_fixes(..., overrides={"<coord>": ""})` to drop, `{"<coord>": "<version>"}`
     to re-target.
5. **Terminal:** report the green build, which findings were applied, and which went to
   manual-review and why. A green build with any unresolved finding is **NEEDS REVIEW**, not
   success. If still red after the cap, stop and report — **never** claim success on red.

A captured end-to-end run is in `examples/spring-boot-sample/RECOVERY.md` (driven by
`advisory-breaking.xlsx`).

## Guardrails

- Stay in v1 scope: Spring Boot **Maven**, **Java** libs (including BOM-managed and
  transitive, via `<dependencyManagement>` pins), up to a green build. Mend API,
  container/OS packages, Gradle, automated PRs, `<exclusions>`-based surgery, and
  auto-applying BOM/parent upgrades are Phase 2 — don't implement them unless asked.
- Keep `core/` deterministic and network-free.
- Be transparent: always relay the skipped-rows log and conflict log, not just the final
  list — that auditability is the point of the tool.
