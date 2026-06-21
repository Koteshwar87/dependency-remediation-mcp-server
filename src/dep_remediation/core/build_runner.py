"""Build runner (Phase 4).

Closes the remediation loop and enforces the project's core rule (plan §8): never claim
success on a broken build. Runs `mvn clean install`, gates on a green build, then runs
`mvn dependency:tree` to confirm each finding's *resolved* version is actually the
recommended one (a `<dependencyManagement>` pin can be silently overridden by a BOM).

Reactor-aware: run at the aggregator root and check resolution across every module.

This is the one `core/` module that shells out. The pure parsers
(`interpret_build`, `parse_resolved_versions`, `build_resolutions`) are Maven-free and
unit-tested; the subprocess runner is injectable so tests never need a live `mvn`.

The automated LLM recovery loop is Phase 2 (§13.3). Here, failures return actionable
context (`log_tail`, `failing_goal`, `attempted`) so the developer's MCP host LLM can
drive recovery via `apply_fixes`/`verify_build`.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, asdict, field

from .advisory_parser import Finding
from .version_compare import compare

_LOG_TAIL_LINES = 40

# dependency:tree line, e.g. "[INFO] +- io.netty:netty-handler:jar:4.2.15.Final:compile"
_TREE_LINE = re.compile(
    r"([\w.\-]+):([\w.\-]+):(?:jar|pom|war|ear|maven-plugin|bundle|test-jar):"
    r"([\w.\-]+)(?::[\w.\-]+)?")
_FAILED_GOAL = re.compile(r"Failed to execute goal .*?:([\w\-]+)\s*\(")


@dataclass
class Resolution:
    coordinate: str
    expected: str
    resolved: str   # "" when the coordinate was not found in the tree
    ok: bool


@dataclass
class BuildResult:
    project_dir: str
    build_passed: bool = False
    exit_code: int = -1
    resolutions: list[Resolution] = field(default_factory=list)
    attempted: list[dict] = field(default_factory=list)  # coordinate->expected, likely culprits on failure
    log_tail: str = ""
    failing_goal: str = ""
    success: bool = False
    message: str = ""

    def to_dict(self):
        return asdict(self)


def interpret_build(returncode: int, output: str):
    """Return (passed, log_tail, failing_goal). Return code is authoritative."""
    passed = returncode == 0
    lines = output.splitlines()
    log_tail = "\n".join(lines[-_LOG_TAIL_LINES:])
    goal = ""
    if not passed:
        m = _FAILED_GOAL.search(output)
        if m:
            goal = m.group(1)
    return passed, log_tail, goal


def parse_resolved_versions(tree_output: str) -> dict[str, set[str]]:
    """Map `groupId:artifactId` -> set of resolved versions seen across all modules.

    Reactor-aware: a root `dependency:tree` emits a section per module, and a coordinate
    can resolve to different versions in different modules, so we collect a set.
    """
    resolved: dict[str, set[str]] = {}
    for group, artifact, version in _TREE_LINE.findall(tree_output):
        resolved.setdefault(f"{group}:{artifact}", set()).add(version)
    return resolved


def build_resolutions(findings, resolved_map: dict[str, set[str]]) -> list[Resolution]:
    """Check each finding's recommended version against what actually resolved."""
    out = []
    for f in findings:
        seen = resolved_map.get(f.coordinate)
        if not seen:
            out.append(Resolution(f.coordinate, f.recommended_version, "", False))
            continue
        # OK only if every resolved version is >= recommended; else record the offender
        offenders = [v for v in seen if compare(v, f.recommended_version) < 0]
        if offenders:
            out.append(Resolution(
                f.coordinate, f.recommended_version,
                sorted(offenders, key=lambda v: v)[0], False))
        else:
            out.append(Resolution(
                f.coordinate, f.recommended_version, sorted(seen)[0], True))
    return out


def _maven_cmd(project_dir: str):
    """Return the base Maven command, preferring a project wrapper. None if not found."""
    if os.name == "nt":
        wrapper = os.path.join(project_dir, "mvnw.cmd")
        if os.path.isfile(wrapper):
            return [wrapper]
    else:
        wrapper = os.path.join(project_dir, "mvnw")
        if os.path.isfile(wrapper):
            return [wrapper]
    mvn = shutil.which("mvn")
    return [mvn] if mvn else None


def _default_runner(goals, cwd):
    """Run Maven `goals` in `cwd`, returning (returncode, merged output).

    Raises FileNotFoundError when no `mvnw` wrapper and no `mvn` on PATH.
    """
    base = _maven_cmd(cwd)
    if base is None:
        raise FileNotFoundError("Maven not found (no mvnw wrapper and `mvn` not on PATH)")
    proc = subprocess.run(base + list(goals), cwd=cwd, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, text=True)
    return proc.returncode, proc.stdout


def verify(project_dir: str, findings=(), *, runner=_default_runner) -> BuildResult:
    """Run `mvn clean install`; if green, verify resolved versions via dependency:tree.

    `runner(goals, cwd) -> (returncode, output)` is injectable so tests need no live Maven.
    """
    findings = list(findings)
    result = BuildResult(
        project_dir=project_dir,
        attempted=[{"coordinate": f.coordinate, "expected": f.recommended_version}
                   for f in findings])

    try:
        rc, out = runner(["clean", "install"], project_dir)
    except FileNotFoundError as e:
        result.message = str(e)
        return result

    result.exit_code = rc
    result.build_passed, result.log_tail, result.failing_goal = interpret_build(rc, out)
    if not result.build_passed:
        result.message = "build failed"
        return result

    if findings:
        _, tree_out = runner(["dependency:tree"], project_dir)
        result.resolutions = build_resolutions(findings, parse_resolved_versions(tree_out))

    result.success = result.build_passed and all(r.ok for r in result.resolutions)
    if not result.success:
        unresolved = [r.coordinate for r in result.resolutions if not r.ok]
        result.message = f"build green but {len(unresolved)} finding(s) not resolved: {unresolved}"
    return result


def print_result(result: BuildResult):
    print(f"Project: {result.project_dir}")
    if result.message and not result.build_passed and result.exit_code == -1:
        print(f"  {result.message}")
        return
    print(f"  Build: {'GREEN' if result.build_passed else 'FAILED'} (exit {result.exit_code})")
    if result.resolutions:
        print("  Resolved versions:")
        for r in result.resolutions:
            status = "OK" if r.ok else f"MISMATCH (resolved {r.resolved or 'absent'})"
            print(f"    {r.coordinate}  expected {r.expected}  {status}")
    verdict = "SUCCESS" if result.success else (
        "BUILD FAILED" if not result.build_passed else "NEEDS REVIEW")
    print(f"  Overall: {verdict}")
    if not result.build_passed:
        if result.failing_goal:
            print(f"  Failing goal: {result.failing_goal}")
        if result.attempted:
            print(f"  Likely culprits (just applied): "
                  + ", ".join(f"{a['coordinate']}->{a['expected']}" for a in result.attempted))
        if result.log_tail:
            print("  --- build log tail ---")
            print(result.log_tail)
