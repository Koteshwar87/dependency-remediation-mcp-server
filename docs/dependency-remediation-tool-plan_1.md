# Vulnerable Dependency Remediation Tool — Plan (v1)

**Status:** Design locked, ready to build
**Scope:** Spring Boot Maven applications
**Last updated:** 2026-06-21

---

## 1. Problem

The security team produces a vulnerability report (Excel export) listing thousands of
flagged dependencies across many applications and across both Java libraries and
container/OS packages. A developer needs to take their app's Java findings, apply the
recommended version upgrades to the Maven `pom.xml`, and confirm the project still
builds — without manually hunting through thousands of rows.

## 2. Goal (v1)

Given the advisory Excel and an app name, the tool will:

1. Filter the sheet down to the app's fixable Java library findings.
2. Extract each library's coordinates, current version, and recommended version.
3. Deduplicate to one target version per library (highest recommended version wins).
4. Apply those version upgrades to the Spring Boot `pom.xml`.
5. Run `mvn clean install` and confirm the build succeeds.

**v1 stops at a successful build.** Raising a PR is explicitly out of scope for v1
(planned as a thin add-on later).

**Deliverable / packaging:** the tool ships as an **MCP (Model Context Protocol)
server** wrapped over a deterministic Python engine. The MCP server is the primary
distribution format — it imports into both VS Code and IntelliJ through their AI
assistants and works with the developer's LLM of choice (LLM-agnostic). A plain CLI
over the same engine is provided as a zero-LLM fallback. (MCP access confirmed available.)

## 3. Non-goals (v1)

- No connection to Mend or any portal/API — the developer supplies the Excel.
- No container/OS package remediation (those are filtered out).
- No Gradle support — Maven only.
- No transitive-dependency resolution — operate on what the advisory lists.
- No automated PR creation.

---

## 4. Architecture

The design separates a deterministic engine from optional LLM assistance, so the tool
is reliable, cheap, portable, and LLM-agnostic.

```
core/                         # LLM-agnostic Python engine (the real product)
├── advisory_parser.py        # read Excel, filter, extract, dedupe -> normalized list
├── version_compare.py        # Maven-aware version comparison
├── pom_fixer.py              # apply version upgrades to pom.xml
└── build_runner.py           # run mvn clean install, interpret result

adapters/                     # thin wrappers over core/
├── cli/                      # plain `python -m core.run` — works with no LLM
└── mcp-server/               # exposes core/ as MCP tools (works in any MCP client)
```

### Design principles

- **Deterministic core.** Parsing, filtering, dedupe, and version comparison are pure
  code — no LLM. This is what makes other teams trust the tool.
- **LLM as optional enhancement, not engine.** The model is only needed for genuinely
  hard judgment (unusual pom structures, build-failure recovery). The tool still works
  without it, just with a larger "needs manual review" bucket.
- **MCP as the distribution layer.** An MCP server built over `core/` imports into both
  VS Code and IntelliJ through their AI assistants and works with the developer's model
  of choice. (Confirmed: MCP access is available.)

---

## 5. Data layer — fully mapped to clean columns

The advisory is a single-tab workbook. Every field the tool needs maps to a clean
column, so **no prose parsing or LLM is required for extraction.**

### Filter chain (reduces thousands of rows to the app's fixable Java libs)

| Step | Column | Rule |
|------|--------|------|
| 1 | `owner` | equals the app the user selected |
| 2 | `Code Library Language` | equals `Java` (blank = container/OS, dropped) |
| 3 | `Base image vulnerability` | equals `FALSE` (cross-check; app lib, not base image) |

### Field extraction (clean column reads — no regex, no LLM)

| Field | Column | Example |
|-------|--------|---------|
| Library identity (`groupId:artifactId`) | `DetailedName` | `org.springframework:spring-core` |
| Current detected version | `Version` | `5.3.32` |
| Version to apply | `RecommendedVersion` | `6.2.11` |

### Reference / context columns (not required for the fix)

- `Description` — templated prose; confirms coordinates, current version, vulnerable
  range, recommended version, and CVE. Useful for reporting and as a fallback only.
- `CVEDescription` — human-readable CVE context.
- `FixedVersion` — observed identical to `RecommendedVersion`; `RecommendedVersion`
  is authoritative if they ever differ (log divergence).
- `Remediation` — the `mvn versions:use-latest-releases -Dincludes=...` command. Not
  executed directly (it pulls "latest", not the specific recommended version).
- `LocationPath`, `ImageId`, `Image layer build command`, `Is Public` — ignored for v1.

---

## 6. Deduplication rule

The same library can appear many times (multiple CVEs, repeated rows).

- **Dedupe key:** `DetailedName` (the `groupId:artifactId`).
- **Conflict resolution:** highest `RecommendedVersion` wins ("always the most-patched
  version"). Defensible and explainable.
- **Transparency:** log every conflict resolved and which versions were compared.

**Version comparison must be Maven-aware**, not string-based. Versions carry qualifiers
(`4.2.13.Final`, `4.2.15.Final`) and naive string sorting is wrong (e.g. `4.2.4` vs
`4.2.15`). The engine uses proper Maven version-ordering semantics.

---

## 7. Pom fixing — the hard part (the moat)

Anyone can bump a `<version>` tag. The real engineering value is correctly applying a
version in a Spring Boot project, where the version may live in:

- a direct `<version>` on the dependency,
- a `<properties>` entry (e.g. `<spring-boot.version>`),
- inherited from `spring-boot-starter-parent`,
- managed in `<dependencyManagement>` / an imported BOM (`<scope>import</scope>`),
- a multi-module reactor where the version sits in the parent pom.

This stage is where the LLM can assist for unusual structures, and where the
"needs manual review" bucket is produced for anything the engine can't safely change.

---

## 8. Build verification

- Run `mvn clean install`.
- **Never** treat the run as done unless the build is green.
- If the build breaks after an upgrade, that case is surfaced (and is the natural place
  for LLM-assisted diagnosis in a later phase).
- Idempotent: re-running must not double-apply changes.

---

## 9. Transparency / trust features

Because the tool edits other teams' code, it must be auditable:

- **Dry-run by default** — show the diff; apply on confirmation.
- **Skipped-rows log** — e.g. "142 rows for app X: 38 Java libraries processed,
  104 container/OS vulns skipped (not pom-fixable)."
- **Conflict log** — which duplicate versions were seen and which won.
- **Clear change report** — per library: from → to, CVE, why this version.
- **Build gating** — no "success" claimed on a failed build.

---

## 10. Open items to confirm

1. Does `RecommendedVersion` ever differ from `FixedVersion`? (Default: trust
   `RecommendedVersion`, log divergence.)
2. Is `DetailedName` always populated for Java rows? (If ever blank, fall back to
   coordinates parsed from `Description`.)
3. Exact `owner` column values vs. how the user names the app at invocation
   (case sensitivity, app-name normalization).

---

## 11. Build phases

| Phase | Deliverable | LLM needed? |
|-------|-------------|-------------|
| 1 | Advisory parser + dedupe engine (filter chain, clean extraction, Maven-aware dedupe, skipped/conflict logs) | No |
| 2 | Maven-aware version comparison module | No |
| 3 | Pom fixer (direct / property / parent / BOM cases) + dry-run diff | Optional (hard cases) |
| 4 | Build runner (`mvn clean install`) + green-build gating | No |
| 5 | MCP server wrapper exposing core/ as tools | No (LLM uses it) |

Phases 1–5 constitute **v1** (manual Excel → fix → green build). Everything beyond v1 —
Mend integration, automated PRs, LLM-assisted build recovery, scale — is captured in
section 13 (Phase 2 roadmap).

**Phase 1 is the immediate next step** — standalone, testable, and independent of the
harder pom work.

---

## 12. Why not existing tools (have this answer ready)

Dependabot, Renovate, Mend native PRs, and OWASP Dependency-Check already scan against
public CVE feeds. The gap this tool fills: it is driven by the **security team's own
curated advisory export** as the source of truth, scoped to the app's Java libraries,
applied through one **LLM-agnostic** interface that works in **any team's IDE**. Keeping
this framing sharp is what justifies building it and drives multi-team adoption.

---

## 13. Phase 2 — future scope (post-v1 roadmap)

Phase 2 begins once v1 is stable and trusted (clean parse → fix → green build, driven by
a manual Excel). The theme of Phase 2 is **removing manual steps and closing the loop**,
without disturbing the deterministic `core/` engine. Each enhancement is an *adapter* or
a *new tool over `core/`* — the engine stays the same, which is what keeps the product
reliable as it grows.

### 13.1 Mend integration (replace the manual Excel)

Goal: the developer no longer exports and drops an Excel; the tool fetches the advisory
live.

- Add `core/advisory_sources/` with a **pluggable source interface**. v1's Excel reader
  becomes one implementation; a new `mend_client.py` becomes another.
- `mend_client.py` calls the Mend REST API for the app's inventory/vulnerabilities and
  **normalizes the response to the exact same internal advisory model** v1 already
  produces. Everything downstream (dedupe, pom fix, build) is unchanged.
- **Credential handling** is the main design decision, not the API call:
  - decide between per-developer Mend tokens vs. a shared service token;
  - never hard-code or commit credentials; read from environment/secret store;
  - this is a security-team policy call — confirm before building.
- **Keep the Excel reader as a permanent fallback** for developers without Mend API
  access. Source is selectable (`--source mend` / `--source excel`).
- Mapping work: confirm which Mend API fields correspond to `DetailedName`,
  `RecommendedVersion`, `owner`, `Code Library Language`, `Base image vulnerability`.

### 13.2 Automated PR creation (close the loop)

Goal: after a green build, raise a clean PR instead of stopping.

- New `core/pr_raiser.py` invoked only after `mvn clean install` passes (build gating
  stays mandatory — never raise a PR on a broken build).
- Mechanics: create a branch (naming convention, e.g. `security/dep-bump-<app>-<date>`),
  commit the pom changes, push, open the PR via `gh` CLI or the Git host API.
- **PR description is part of the product** — auto-generate a table: each library,
  from → to version, CVE id(s), severity, and why this version was chosen (the dedupe
  decision). This is what makes reviewers trust and merge it quickly.
- Idempotency: re-running must update the existing branch/PR, not spawn duplicates.
- Config: base branch, branch-name template, reviewers/labels, draft vs. ready.

### 13.3 LLM-assisted build-failure recovery

Goal: shrink the "needs manual review" bucket by letting the model diagnose and fix
breakages an upgrade introduces.

- When `mvn clean install` fails post-upgrade, hand the build log + diff + pom context
  to the LLM (through the MCP/adapter layer) to propose a corrective change
  (e.g. an aligned transitive bump, a needed property change, an exclusion).
- Always **re-run the build** to verify the LLM's fix; never trust it blindly.
- Cap the retry loop (e.g. 2–3 attempts) and fall back to manual review with a clear
  explanation of what was tried.
- This is the one place model quality matters — but it remains an *enhancement*: the
  deterministic path still produces value without it.

### 13.4 Broader pom-structure coverage

Goal: handle the long tail of Spring Boot project shapes the v1 fixer punts on.

- Deeper multi-module reactor support (version declared in a parent/aggregator pom).
- Imported BOM alignment (bump the BOM rather than individual managed deps where that
  is the correct fix).
- Property-indirection chains and profiles.
- Each added case ships with tests against real-world pom fixtures.

### 13.5 Scale and distribution

Goal: make it a true multi-team product, not a single-repo helper.

- **CI/pipeline mode:** a headless entry point so the same `core/` can run in Jenkins or
  any CI (scheduled scans → auto-PR), independent of any IDE or LLM. (Note: this does
  **not** require Claude Code on the CI server — the engine is plain Python.)
- **Config per team:** advisory source, dedupe/conflict policy, PR conventions, and
  filters expressed in a per-repo config file so teams self-onboard.
- **Gradle support** as a parallel fixer implementation behind the same engine, if
  demand exists.
- **Reporting/metrics:** track vulns remediated, PRs raised, manual-review rate — useful
  for showing impact to leadership and other teams.

### 13.6 Phase 2 sequencing (suggested)

| Order | Enhancement | Rationale |
|-------|-------------|-----------|
| 1 | Automated PR creation (13.2) | Highest value, lowest risk; builds on a green build |
| 2 | LLM-assisted build recovery (13.3) | Directly shrinks manual-review bucket |
| 3 | Mend integration (13.1) | Removes the manual step; gated on credential policy |
| 4 | Broader pom coverage (13.4) | Continuous; widens applicability |
| 5 | Scale / CI / config / Gradle (13.5) | Productization for multi-team adoption |

**Guiding constraint for all of Phase 2:** the deterministic `core/` engine and the
"never claim success on a broken build" rule are invariant. Every enhancement is added
as a pluggable source, a new tool over `core/`, or an adapter — never by compromising the
trustworthy core.
