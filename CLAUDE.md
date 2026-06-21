# CLAUDE.md

Guidance for Claude Code (and any AI assistant) working in this repository.

## What this project is

A **vulnerable dependency remediation tool** for Spring Boot Maven apps. It reads a
security team's vulnerability advisory (Excel export), scopes it to one app's fixable
Java library findings, applies the recommended version upgrades to `pom.xml`, and
confirms `mvn clean install` still passes.

The full, authoritative design lives in
[`dependency-remediation-tool-plan_1.md`](dependency-remediation-tool-plan_1.md).
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

In scope: Spring Boot **Maven**, **Java library** findings, up to a green build.
Out of scope (do not implement without being asked): Mend/portal APIs, container/OS
package fixes, Gradle, transitive resolution, automated PRs. These are Phase 2 — see
section 13 of the plan.

## Current layout

The code is currently flat at the repo root; it will migrate under `core/` as the
engine grows (target layout is in the plan and README).

| File | Phase | Purpose |
|------|-------|---------|
| `advisory_parser.py` | 1 ✅ | Read Excel, apply filter chain, extract fields, dedupe → `Report` |
| `version_compare.py` | 2 ✅ | Maven-aware `compare()` / `max_version()` |
| `pom_fixer.py` | 3 ⬜ | Apply version upgrades to `pom.xml` (direct / property / parent / BOM) |
| `build_runner.py` | 4 ⬜ | Run `mvn clean install`, interpret result, gate on green |
| `adapters/cli`, `adapters/mcp-server` | 5 ⬜ | Thin wrappers over `core/` |

`advisory_parser.py` imports from `version_compare.py`. Keep them importable as a pair
(if you move one under `core/`, update the import and any adapter).

## Data model

The advisory is a single-tab workbook. The engine reads clean columns only — no prose
parsing for the fix. Column names are centralized as `COL_*` constants in
`advisory_parser.py`; a sheet rename should be a one-line change there.

- Filter chain: `owner` == app, `Code Library Language` == `Java`,
  `Base image vulnerability` == `FALSE`.
- Extract: `DetailedName` (groupId:artifactId), `Version`, `RecommendedVersion`.
- Dedupe key: `DetailedName`; conflict resolution: **highest `RecommendedVersion`
  wins**, compared Maven-aware; log every conflict.
- `RecommendedVersion` is authoritative over `FixedVersion` (log divergence). If
  `DetailedName` is blank, fall back to coordinates from `Description` backticks.

## Commands

```bash
pip install -r requirements.txt

# Parse an advisory for an app
python advisory_parser.py dummy_advisory.xlsx --app app-alpha [--json] [--no-base-image-filter]

# Version-comparison self-tests
python version_compare.py
```

`dummy_advisory.xlsx` is the local sample fixture (app `app-alpha`).

## Conventions

- Python 3.11+; standard library + `pandas`/`openpyxl` for the engine.
- Keep modules deterministic and unit-testable; prefer pure functions returning
  dataclasses (`Finding`, `Conflict`, `Report`) over side effects.
- When adding a new pom-structure case or version edge case, add a fixture/test for it.
- Don't introduce a network call into `core/`. Sources (Excel today, Mend later) belong
  behind a pluggable source interface (Phase 2.1).
