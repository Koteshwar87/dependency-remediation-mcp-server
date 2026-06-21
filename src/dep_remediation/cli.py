"""Plain CLI adapter over the deterministic engine — works with no LLM.

Entry point: `dep-remediation` (see pyproject [project.scripts]) or
`python -m dep_remediation.cli`.
"""
from __future__ import annotations
import argparse
import json

from .core.advisory_parser import parse, print_report


def main():
    ap = argparse.ArgumentParser(
        description="Parse a security advisory Excel -> normalized fix list"
    )
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
