"""Generate `advisory.xlsx` for the Spring Boot sample app.

Mirrors the column schema the engine reads (the `COL_*` constants in
`dep_remediation.core.advisory_parser`). Run from anywhere:

    python examples/spring-boot-sample/make_advisory.py

It writes `advisory.xlsx` next to this script. The four real findings (owner
`sample-app`, language `Java`) each exercise a different pom resolution class; the
extra rows are deliberate noise to exercise the parser's filter chain.
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook

# Column headers — must match dep_remediation.core.advisory_parser COL_* constants.
HEADERS = [
    "owner",
    "Code Library Language",
    "DetailedName",
    "Version",
    "RecommendedVersion",
    "FixedVersion",
    "Base image vulnerability",
    "Description",
]

# owner, language, name, version, recommended, fixed, base_image, description
ROWS = [
    # --- 4 real findings for `sample-app`, one per resolution class ---
    ("sample-app", "Java", "org.apache.commons:commons-text", "1.9", "1.10.0", "1.10.0",
     "FALSE", "Vulnerable `org.apache.commons:commons-text` (direct <version>) — CVE-2022-42889."),
    ("sample-app", "Java", "org.apache.commons:commons-collections4", "4.1", "4.4", "4.4",
     "FALSE", "Vulnerable `org.apache.commons:commons-collections4` (property-driven version)."),
    ("sample-app", "Java", "org.yaml:snakeyaml", "2.2", "2.3", "2.3",
     "FALSE", "Vulnerable `org.yaml:snakeyaml` (managed by the Spring Boot parent BOM)."),
    ("sample-app", "Java", "org.apache.tomcat.embed:tomcat-embed-core", "10.1.24", "10.1.25", "10.1.25",
     "FALSE", "Vulnerable `org.apache.tomcat.embed:tomcat-embed-core` (purely transitive)."),
    # --- noise: should be filtered out ---
    ("other-app", "Java", "com.fasterxml.jackson.core:jackson-databind", "2.13.0", "2.15.4", "2.15.4",
     "FALSE", "Different owner — must be skipped (other owner)."),
    ("sample-app", "", "alpine", "3.16", "3.19", "3.19",
     "FALSE", "Blank language — container/OS package, must be skipped."),
    ("sample-app", "Java", "org.example:base-only", "1.0", "1.1", "1.1",
     "TRUE", "Base image vulnerability — must be skipped by the base-image filter."),
]


def main() -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "advisory"
    ws.append(HEADERS)
    for row in ROWS:
        ws.append(list(row))
    out = Path(__file__).with_name("advisory.xlsx")
    wb.save(out)
    print(f"wrote {out}  ({len(ROWS)} rows)")


if __name__ == "__main__":
    main()
