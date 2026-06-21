"""Advisory parser + dedupe engine (Phase 1).

Reads the security advisory Excel, applies the filter chain, extracts the three
fields we need from clean columns, and dedupes to one target version per library
(highest RecommendedVersion wins, Maven-aware).

Designed to be deterministic and LLM-free. Emits a normalized advisory list plus
transparency logs (skipped rows, resolved conflicts).
"""
from __future__ import annotations
import argparse
import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

import pandas as pd

from version_compare import version_key

# Column names as seen in the real sheet. Centralized so a rename is a one-line fix.
COL_OWNER = "owner"
COL_LANG = "Code Library Language"
COL_NAME = "DetailedName"
COL_VERSION = "Version"
COL_RECOMMENDED = "RecommendedVersion"
COL_FIXED = "FixedVersion"
COL_BASE_IMG_VULN = "Base image vulnerability"
COL_DESCRIPTION = "Description"

JAVA_LANG = "java"

# Fallback: pull groupId:artifactId from the Description backticks if DetailedName is blank.
_DESC_COORD = re.compile(r"library\s+`([\w.\-]+:[\w.\-]+)`", re.IGNORECASE)


@dataclass
class Finding:
    coordinate: str          # groupId:artifactId
    current_version: str
    recommended_version: str


@dataclass
class Conflict:
    coordinate: str
    chosen: str
    candidates: list[str]


@dataclass
class Report:
    app: str
    findings: list[Finding] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    rows_total: int = 0
    rows_for_app: int = 0
    rows_java: int = 0
    rows_skipped_lang: int = 0
    rows_skipped_owner: int = 0
    rows_skipped_base_image: int = 0
    rows_missing_data: int = 0

    def to_dict(self):
        d = asdict(self)
        return d


def _norm(x) -> str:
    if x is None or (not isinstance(x, str) and pd.isna(x)):
        return ""
    return str(x).strip()


def _coord_for_row(row) -> str:
    name = _norm(row.get(COL_NAME))
    if name:
        return name
    m = _DESC_COORD.search(_norm(row.get(COL_DESCRIPTION)))
    return m.group(1) if m else ""


def parse(xlsx_path: str, app: str, *, base_image_filter: bool = True) -> Report:
    df = pd.read_excel(xlsx_path, dtype=str)
    rep = Report(app=app, rows_total=len(df))

    target_owner = app.strip().lower()
    # group recommended versions per coordinate, after filtering
    by_coord: dict[str, dict] = {}

    for _, row in df.iterrows():
        owner = _norm(row.get(COL_OWNER)).lower()
        if owner != target_owner:
            rep.rows_skipped_owner += 1
            continue
        rep.rows_for_app += 1

        lang = _norm(row.get(COL_LANG)).lower()
        if lang != JAVA_LANG:
            rep.rows_skipped_lang += 1   # blank = container/OS
            continue
        rep.rows_java += 1

        if base_image_filter and _norm(row.get(COL_BASE_IMG_VULN)).lower() == "true":
            rep.rows_skipped_base_image += 1
            continue

        coord = _coord_for_row(row)
        rec = _norm(row.get(COL_RECOMMENDED)) or _norm(row.get(COL_FIXED))
        cur = _norm(row.get(COL_VERSION))
        if not coord or not rec:
            rep.rows_missing_data += 1
            continue

        entry = by_coord.setdefault(coord, {"current": cur, "recs": set()})
        entry["recs"].add(rec)
        if not entry["current"]:
            entry["current"] = cur

    for coord in sorted(by_coord):
        recs = sorted(by_coord[coord]["recs"], key=version_key)  # ascending, Maven-aware
        chosen = recs[-1]                                        # highest wins
        rep.findings.append(Finding(
            coordinate=coord,
            current_version=by_coord[coord]["current"],
            recommended_version=chosen,
        ))
        if len(recs) > 1:
            rep.conflicts.append(Conflict(coordinate=coord, chosen=chosen, candidates=recs))

    return rep


def print_report(rep: Report):
    print(f"App: {rep.app}")
    print(f"  Rows in sheet:           {rep.rows_total}")
    print(f"  Rows for this app:       {rep.rows_for_app}")
    print(f"  Java library rows:       {rep.rows_java}")
    print(f"  Skipped (other owner):   {rep.rows_skipped_owner}")
    print(f"  Skipped (container/OS):  {rep.rows_skipped_lang}")
    print(f"  Skipped (base image):    {rep.rows_skipped_base_image}")
    print(f"  Skipped (missing data):  {rep.rows_missing_data}")
    print()
    print(f"Unique libraries to fix: {len(rep.findings)}")
    print(f"  {'LIBRARY':<48} {'CURRENT':<14} -> RECOMMENDED")
    for f in rep.findings:
        print(f"  {f.coordinate:<48} {f.current_version:<14} -> {f.recommended_version}")
    if rep.conflicts:
        print()
        print(f"Conflicts resolved (highest version wins): {len(rep.conflicts)}")
        for c in rep.conflicts:
            print(f"  {c.coordinate}: chose {c.chosen}  from {c.candidates}")


def main():
    ap = argparse.ArgumentParser(description="Parse security advisory Excel -> normalized fix list")
    ap.add_argument("xlsx", help="path to advisory .xlsx")
    ap.add_argument("--app", required=True, help="owner/app name to filter by")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--no-base-image-filter", action="store_true",
                    help="do not skip rows where Base image vulnerability = TRUE")
    args = ap.parse_args()

    rep = parse(args.xlsx, args.app, base_image_filter=not args.no_base_image_filter)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2))
    else:
        print_report(rep)


if __name__ == "__main__":
    main()
