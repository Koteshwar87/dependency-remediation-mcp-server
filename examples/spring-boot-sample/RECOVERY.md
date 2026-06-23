# Build-failure recovery — captured run (multi-module reactor)

Demonstrates the **recovery loop** on a real red reactor build (live Maven 3.8.1 / Java 17).
The driver is `advisory-breaking.xlsx` — identical to `advisory.xlsx` except the
`commons-text` finding recommends a **non-existent version (`99.0.0`)**, modelling a yanked
or typo'd advisory entry. `commons-text` lives in `sample-core`, so the failure surfaces
there and aborts the reactor. Run against a throwaway copy.

## Attempt 1 — apply everything, the reactor goes red

Targeted fix as in the happy path (direct/property in `sample-core`, pins in the aggregator),
but with the bad `commons-text 99.0.0`:

```
$ dep-remediation verify . --from-advisory advisory-breaking.xlsx --app sample-app
  Build: FAILED (exit 1)
  Overall: BUILD FAILED
  Failure kind: dependency_resolution
  Suspect coordinates: org.apache.commons:commons-text
  Likely culprits (just applied): ...commons-text->99.0.0...
  --- build log tail ---
  [ERROR] Failed to execute goal on project sample-core: Could not resolve dependencies ...
          org.apache.commons:commons-text:jar:99.0.0 was not found ...
  [ERROR]   mvn <args> -rf :sample-core
```

The classifier reports `failure_kind = dependency_resolution` and pins the **suspect** to
`org.apache.commons:commons-text` — even though Maven phrased it as a *cached* "was not
found" (reactor re-runs hit the cached failure), and it did **not** mistake the project's own
coordinate (`com.example:sample-core:jar:1.0.0`) for the culprit.

## Diagnosis (the judgment step — host LLM)

`dependency_resolution` means the recommended version can't be fetched (yanked / typo / wrong
repo). v1 does not auto-discover a replacement, so the safe move is to **drop** the suspect
to manual-review and keep the rest.

## Attempt 2 — re-apply the curated set (skip the suspect)

Re-applied against a **fresh copy** (the engine does not revert):

```
$ dep-remediation fix sample-core/pom.xml --from-advisory advisory-breaking.xlsx --app sample-app \
      --skip org.apache.commons:commons-text \
      --skip org.yaml:snakeyaml --skip org.apache.tomcat.embed:tomcat-embed-core --apply
Actions: 1
  [property/edit-property] org.apache.commons:commons-collections4: 4.1 -> 4.4
# (aggregator pins for snakeyaml + tomcat-embed-core applied as in the happy path)

$ dep-remediation verify . --from-advisory advisory-breaking.xlsx --app sample-app
  Build: GREEN (exit 0)
    org.apache.commons:commons-collections4   expected 4.4      OK
    org.apache.commons:commons-text           expected 99.0.0   MISMATCH (resolved 1.9)
    org.apache.tomcat.embed:tomcat-embed-core expected 10.1.25  OK
    org.yaml:snakeyaml                        expected 2.3      OK
  Overall: NEEDS REVIEW
```

## Terminal state (honest)

The reactor is **green** with 3 of 4 findings remediated across both modules; `commons-text`
is surfaced as **NEEDS REVIEW** (its advised version doesn't exist). The run is **not**
reported as success — a green build with an unresolved finding is `NEEDS REVIEW`, never
`SUCCESS`. See the `remediate-dependencies` skill for the bounded loop the host LLM drives.
