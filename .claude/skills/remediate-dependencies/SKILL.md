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

- **Advisory Excel** path (e.g. `dummy_advisory.xlsx`).
- **App / owner name** as it appears in the `owner` column (case-insensitive match).
- For the fix step: path to the target Spring Boot project's `pom.xml`.

If the app name or Excel path is missing and not obvious, ask before running.

## Steps

### 1. Parse + dedupe (Phase 1 — available now)

```bash
python advisory_parser.py <advisory.xlsx> --app <owner> --json
```

Report back from the output:
- counts (total rows, rows for app, Java rows, skipped owner/lang/base-image/missing),
- the unique libraries to fix (`coordinate`, `current_version` → `recommended_version`),
- every conflict resolved (which candidate versions were seen, which won and why —
  highest `RecommendedVersion`, Maven-aware).

Do not hand-edit the dedupe result; if a chosen version looks wrong, check it with
`version_compare.compare` rather than overriding by eye.

### 2. Apply to pom.xml (Phase 3 — `pom_fixer.py`, not built yet)

When implemented: run **dry-run first**, show the diff, apply only on confirmation.
Versions may live in a direct `<version>`, a `<properties>` entry, the
`spring-boot-starter-parent`, `<dependencyManagement>`/imported BOM, or a parent pom in
a reactor. Anything the engine can't safely place goes into the **needs-manual-review**
bucket — list it explicitly; never guess-edit.

### 3. Verify the build (Phase 4 — `build_runner.py`, not built yet)

```bash
mvn clean install
```

**Never report success unless the build is green.** If it breaks, surface the failure
(and the diff that caused it). Re-running must be idempotent — no double-applied bumps.

## Guardrails

- Stay in v1 scope: Spring Boot **Maven**, **Java** libs, up to a green build. Mend API,
  container/OS packages, Gradle, transitive resolution, and automated PRs are Phase 2 —
  don't implement them unless asked.
- Keep `core/` deterministic and network-free.
- Be transparent: always relay the skipped-rows log and conflict log, not just the final
  list — that auditability is the point of the tool.
