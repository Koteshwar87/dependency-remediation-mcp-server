# Build-failure recovery — captured run

Demonstrates the **recovery loop** on a real red build (live Maven 3.8.1 / Java 17). The
driver is `advisory-breaking.xlsx` — identical to `advisory.xlsx` except the `commons-text`
finding recommends a **non-existent version (`99.0.0`)**, modelling a yanked or typo'd
advisory entry. Run against a throwaway copy of the sample.

## Attempt 1 — apply everything, build goes red

```
$ dep-remediation fix <copy>/pom.xml --from-advisory advisory-breaking.xlsx --app sample-app --apply
Actions: 4
  [property/edit-property] org.apache.commons:commons-collections4: 4.1 -> 4.4
  [direct/edit-version]    org.apache.commons:commons-text: 1.9 -> 99.0.0
  [transitive/add-pin]     org.apache.tomcat.embed:tomcat-embed-core: ... -> 10.1.25
  [managed/add-pin]        org.yaml:snakeyaml: ... -> 2.3
Applied: True

$ dep-remediation verify <copy> --from-advisory advisory-breaking.xlsx --app sample-app
  Build: FAILED (exit 1)
  Overall: BUILD FAILED
  Failure kind: dependency_resolution
  Suspect coordinates: org.apache.commons:commons-text
  Likely culprits (just applied): ...commons-text->99.0.0...
  --- build log tail ---
  [ERROR] Could not find artifact org.apache.commons:commons-text:jar:99.0.0 in central
```

The deterministic classifier turns the Maven log into a **reasoning-ready** signal:
`failure_kind = dependency_resolution` and the **suspect coordinate**
`org.apache.commons:commons-text` — no log-scraping needed by the host LLM.

## Diagnosis (the judgment step — host LLM)

A `dependency_resolution` failure means the recommended version cannot be fetched (yanked /
typo / wrong repo). v1 does not auto-discover a replacement, so the safe move is to **drop**
the suspect finding to manual-review and keep the rest.

## Attempt 2 — re-apply the curated set (skip the suspect)

Re-applied against a **fresh copy** (the engine does not revert; each attempt starts from a
clean baseline):

```
$ dep-remediation fix <fresh-copy>/pom.xml --from-advisory advisory-breaking.xlsx --app sample-app \
      --skip org.apache.commons:commons-text --apply
Actions: 3
  [property/edit-property] org.apache.commons:commons-collections4: 4.1 -> 4.4
  [transitive/add-pin]     org.apache.tomcat.embed:tomcat-embed-core: ... -> 10.1.25
  [managed/add-pin]        org.yaml:snakeyaml: ... -> 2.3
Applied: True

$ dep-remediation verify <fresh-copy> --from-advisory advisory-breaking.xlsx --app sample-app
  Build: GREEN (exit 0)
  Resolved versions:
    org.apache.commons:commons-collections4   expected 4.4      OK
    org.apache.commons:commons-text           expected 99.0.0   MISMATCH (resolved 1.9)
    org.apache.tomcat.embed:tomcat-embed-core expected 10.1.25  OK
    org.yaml:snakeyaml                        expected 2.3      OK
  Overall: NEEDS REVIEW
```

## Terminal state (honest)

Build is **green** with 3 of 4 findings remediated; `commons-text` is surfaced as
**NEEDS REVIEW** (its advised version doesn't exist). The run is **not** reported as
success — a green build with an unresolved finding is `NEEDS REVIEW`, never `SUCCESS`. That
is the rule: never claim success on a broken or incompletely-remediated build.

The same loop is what the host LLM drives via the `apply_fixes` (with `overrides`) and
`verify_build` MCP tools — see the `remediate-dependencies` skill for the bounded algorithm.
