# End-to-end shakeout — captured run

First real run of the full pipeline (parse → fix → green build + resolved-version check)
against a **real Spring Boot Maven project and live Maven** (Apache Maven 3.8.1, Java 17),
not fixtures. This is the evidence the happy path works end to end.

The committed sample stays in its **"before" (vulnerable)** state; the apply + verify steps
were run against a throwaway copy.

## 1. Parse the advisory

```
$ dep-remediation parse examples/spring-boot-sample/advisory.xlsx --app sample-app

App: sample-app
  Rows in sheet:           7
  Rows for this app:       6
  Java library rows:       5
  Skipped (other owner):   1
  Skipped (container/OS):  1
  Skipped (base image):    1
  Skipped (missing data):  0

Unique libraries to fix: 4
  LIBRARY                                          CURRENT        -> RECOMMENDED
  org.apache.commons:commons-collections4          4.1            -> 4.4
  org.apache.commons:commons-text                  1.9            -> 1.10.0
  org.apache.tomcat.embed:tomcat-embed-core        10.1.24        -> 10.1.25
  org.yaml:snakeyaml                               2.2            -> 2.3
```

The three noise rows (other owner / blank-language container row / base-image=TRUE) are
each filtered out for the right reason.

## 2. Fix (dry-run) — one action per resolution class

```
$ dep-remediation fix examples/spring-boot-sample/pom.xml \
      --from-advisory examples/spring-boot-sample/advisory.xlsx --app sample-app

Actions: 4
  [property/edit-property] org.apache.commons:commons-collections4: 4.1 -> 4.4
  [direct/edit-version]    org.apache.commons:commons-text: 1.9 -> 1.10.0
  [transitive/add-pin]     org.apache.tomcat.embed:tomcat-embed-core: (managed/transitive) -> 10.1.25  (added <dependencyManagement> pin)
  [managed/add-pin]        org.yaml:snakeyaml: (managed/transitive) -> 2.3  (added <dependencyManagement> pin)
Applied: False
```

All four resolution classes the classifier supports are exercised:
**direct** literal `<version>`, **property**-sourced version, **managed** (versionless,
owned by the Boot parent BOM), and purely **transitive** — the last two remediated with a
`<dependencyManagement>` pin.

## 3. Apply + verify against live Maven

```
$ dep-remediation verify <copy> --from-advisory examples/spring-boot-sample/advisory.xlsx --app sample-app

  Build: GREEN (exit 0)
  Resolved versions:
    org.apache.commons:commons-collections4  expected 4.4      OK
    org.apache.commons:commons-text          expected 1.10.0   OK
    org.apache.tomcat.embed:tomcat-embed-core expected 10.1.25  OK
    org.yaml:snakeyaml                       expected 2.3      OK
  Overall: SUCCESS
```

`mvn clean install` is green **and** `mvn dependency:tree` confirms every finding resolved
to the recommended version (including the two enforced via a pin).

## Observations (feed into the next iteration)

- **Wrapper invocation is fragile.** `core/build_runner.py` prefers a project `mvnw`/
  `mvnw.cmd`. On this Windows run the wrapper's first-time self-provisioning failed in the
  temp working dir (`fail to move MAVEN_HOME` / `Cannot start maven from wrapper`). System
  `mvn` worked fine, so verification was completed via the existing `shutil.which("mvn")`
  fallback. **Follow-up:** when the wrapper fails to *launch* (vs. a genuine build failure),
  `build_runner` should fall back to system `mvn` rather than reporting a build failure.
- The happy path is now proven; the next feature — **LLM-driven build-failure recovery** —
  needs a *failing* bump to react to. A deliberately incompatible recommended version (e.g.
  a major bump that breaks the API the sample calls) should be added as a second scenario
  to drive that work.
