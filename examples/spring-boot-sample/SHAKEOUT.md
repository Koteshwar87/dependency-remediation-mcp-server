# End-to-end shakeout — captured run (multi-module reactor)

Full pipeline (parse → targeted fix → green build + cross-module resolution check) against
the **multi-module reactor** sample on **live Maven** (Apache Maven 3.8.1, Java 17). This is
the evidence the reactor-aware path works end to end, not just on fixtures.

The committed sample stays in its **"before" (vulnerable)** state; the fix + verify steps
run against a throwaway copy.

## Module layout and where each finding lives

```
spring-boot-sample/        aggregator (packaging pom) — managed/transitive pins go here
├── sample-core/           commons-text 1.9 (DIRECT) + commons-collections4 4.1 (PROPERTY)
└── sample-web/            snakeyaml (MANAGED) + tomcat-embed-core 10.1.24 (TRANSITIVE via starter-web)
```

`commons-text` / `commons-collections4` / `snakeyaml` resolve in **both** modules
(`sample-web` depends on `sample-core`), so the resolution check below spans the whole reactor.

## 1. Parse — unchanged (4 findings)

```
$ dep-remediation parse advisory.xlsx --app sample-app
Unique libraries to fix: 4
  org.apache.commons:commons-collections4   4.1      -> 4.4
  org.apache.commons:commons-text           1.9      -> 1.10.0
  org.apache.tomcat.embed:tomcat-embed-core 10.1.24  -> 10.1.25
  org.yaml:snakeyaml                        2.2      -> 2.3
```

## 2. Fix — one command, auto-targeted across the reactor

Point `fix` at the project; the engine routes each finding to the right pom on its own (a
`<dependencyManagement>` pin can't override a module's explicit `<version>`, so direct/property
findings are edited in the declaring module and managed/transitive ones are pinned in the
aggregator):

```
$ dep-remediation fix . --from-advisory advisory.xlsx --app sample-app --apply
Reactor: ./pom.xml  (3 poms)
Pom: ./pom.xml
  [transitive/add-pin] org.apache.tomcat.embed:tomcat-embed-core: ... -> 10.1.25
  [transitive/add-pin] org.yaml:snakeyaml: ... -> 2.3
Pom: ./sample-core/pom.xml
  [property/edit-property] org.apache.commons:commons-collections4: 4.1 -> 4.4
  [direct/edit-version]    org.apache.commons:commons-text: 1.9 -> 1.10.0
Pom: ./sample-web/pom.xml
  (no changes)
```

No `--skip`, no per-module commands — `sample-web` correctly gets nothing (its snakeyaml is
pinned in the aggregator and inherited).

## 3. Verify at the aggregator root — reactor-wide

```
$ dep-remediation verify . --from-advisory advisory.xlsx --app sample-app
  Build: GREEN (exit 0)
  Resolved versions:
    org.apache.commons:commons-collections4   expected 4.4      OK
    org.apache.commons:commons-text           expected 1.10.0   OK
    org.apache.tomcat.embed:tomcat-embed-core expected 10.1.25  OK
    org.yaml:snakeyaml                        expected 2.3      OK
  Overall: SUCCESS
```

`mvn clean install` is green across the whole reactor **and** `mvn dependency:tree` confirms
every finding resolved to the recommended version **in every module it appears in** — the
per-module sections are aggregated, so a mismatch in any module would be caught.
