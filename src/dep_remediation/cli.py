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
import os

from .core.advisory_parser import parse, print_report
from .core.pom_fixer import apply_fixes, print_result
from .core import build_runner


def _cmd_parse(args):
    rep = parse(args.xlsx, args.app, base_image_filter=not args.no_base_image_filter)
    if args.json:
        print(json.dumps(rep.to_dict(), indent=2))
    else:
        print_report(rep)


def _cmd_fix(args):
    if args.verify and not args.apply:
        raise SystemExit("--verify requires --apply (nothing is written in a dry-run)")
    rep = parse(args.from_advisory, args.app,
                base_image_filter=not args.no_base_image_filter)
    result = apply_fixes(args.pom, rep.findings, dry_run=not args.apply)
    build = None
    if args.verify and result.applied:
        build = build_runner.verify(os.path.dirname(args.pom) or ".", rep.findings)
    if args.json:
        out = {"fix": result.to_dict()}
        if build is not None:
            out["verify"] = build.to_dict()
        print(json.dumps(out, indent=2))
    else:
        print_result(result)
        if build is not None:
            print()
            build_runner.print_result(build)


def _cmd_verify(args):
    findings = ()
    if args.from_advisory and args.app:
        findings = parse(args.from_advisory, args.app,
                         base_image_filter=not args.no_base_image_filter).findings
    result = build_runner.verify(args.project_dir, findings)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        build_runner.print_result(result)


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
    f.add_argument("--verify", action="store_true",
                   help="after --apply, run mvn clean install + dependency:tree to gate the build")
    f.add_argument("--json", action="store_true", help="emit JSON instead of text")
    f.add_argument("--no-base-image-filter", action="store_true",
                   help="do not skip rows where Base image vulnerability = TRUE")
    f.set_defaults(func=_cmd_fix)

    v = sub.add_parser("verify", help="build a project (mvn clean install) + check resolved versions")
    v.add_argument("project_dir", help="path to the Maven project (aggregator root for a reactor)")
    v.add_argument("--from-advisory", help="advisory .xlsx (enables the resolved-version check)")
    v.add_argument("--app", help="owner/app name to filter by (with --from-advisory)")
    v.add_argument("--json", action="store_true", help="emit JSON instead of text")
    v.add_argument("--no-base-image-filter", action="store_true",
                   help="do not skip rows where Base image vulnerability = TRUE")
    v.set_defaults(func=_cmd_verify)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
