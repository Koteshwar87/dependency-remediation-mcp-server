"""Plain CLI adapter over the deterministic engine — works with no LLM.

Entry point: `dep-remediation` (see pyproject [project.scripts]) or
`python -m dep_remediation.cli`.

Subcommands:
  parse  <xlsx> --app <app>                          -> deduped fix list
  fix    <pom>  --from-advisory <xlsx> --app <app>   -> classify + apply upgrades
"""
from __future__ import annotations
import argparse
import json

from .core.advisory_parser import parse, print_report
from .core.pom_fixer import apply_fixes, print_result


def _cmd_parse(args):
    rep = parse(args.xlsx, args.app, base_image_filter=not args.no_base_image_filter)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2))
    else:
        print_report(rep)


def _cmd_fix(args):
    rep = parse(args.from_advisory, args.app,
                base_image_filter=not args.no_base_image_filter)
    result = apply_fixes(args.pom, rep.findings, dry_run=not args.apply)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print_result(result)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="dep-remediation",
        description="Remediate vulnerable Java dependencies from a security advisory")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="parse an advisory Excel -> normalized fix list")
    p.add_argument("xlsx", help="path to advisory .xlsx")
    p.add_argument("--app", required=True, help="owner/app name to filter by")
    p.add_argument("--json", action="store_true", help="emit JSON instead of text")
    p.add_argument("--no-base-image-filter", action="store_true",
                   help="do not skip rows where Base image vulnerability = TRUE")
    p.set_defaults(func=_cmd_parse)

    f = sub.add_parser("fix", help="apply advisory upgrades to a pom.xml")
    f.add_argument("pom", help="path to the Spring Boot pom.xml")
    f.add_argument("--from-advisory", required=True, help="path to advisory .xlsx")
    f.add_argument("--app", required=True, help="owner/app name to filter by")
    f.add_argument("--apply", action="store_true",
                   help="write changes (default is dry-run: show the diff only)")
    f.add_argument("--json", action="store_true", help="emit JSON instead of text")
    f.add_argument("--no-base-image-filter", action="store_true",
                   help="do not skip rows where Base image vulnerability = TRUE")
    f.set_defaults(func=_cmd_fix)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
