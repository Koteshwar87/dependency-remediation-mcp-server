"""Focused tests for the Phase 4 build runner.

Pure parsers are tested against captured Maven output; `verify()` is tested with a fake
runner so no live Maven is needed.
"""
from __future__ import annotations
from pathlib import Path

from dep_remediation.core.advisory_parser import Finding
from dep_remediation.core import build_runner as br

MAVEN = Path(__file__).parent / "fixtures" / "maven"


def _read(name):
    return (MAVEN / name).read_text(encoding="utf-8")


def _findings():
    return [
        Finding("io.netty:netty-handler", "4.2.4.Final", "4.2.15.Final"),
        Finding("com.fasterxml.jackson.core:jackson-databind", "2.13.0", "2.15.4"),
    ]


def _fake_runner(build_out, build_rc=0, tree_out=""):
    def run(goals, cwd):
        if "dependency:tree" in goals:
            return 0, tree_out
        return build_rc, build_out
    return run


def test_interpret_build_pass():
    passed, tail, goal = br.interpret_build(0, _read("build-success.txt"))
    assert passed and goal == "" and "BUILD SUCCESS" in tail


def test_interpret_build_fail_extracts_goal():
    passed, tail, goal = br.interpret_build(1, _read("build-failure.txt"))
    assert not passed
    assert goal == "compile"
    assert "Compilation failure" in tail


def test_classify_failure_resolution_extracts_suspect():
    kind, suspects = br.classify_failure(_read("build-failure-resolution.txt"))
    assert kind == br.DEPENDENCY_RESOLUTION
    assert "org.apache.commons:commons-text" in suspects


def test_classify_failure_compilation():
    kind, suspects = br.classify_failure(_read("build-failure.txt"), failing_goal="compile")
    assert kind == br.COMPILATION
    assert suspects == []


def test_classify_failure_unknown():
    kind, suspects = br.classify_failure("some unrelated output", failing_goal="")
    assert kind == br.UNKNOWN and suspects == []


def test_verify_resolution_failure_sets_kind_and_suspects(tmp_path):
    runner = _fake_runner(_read("build-failure-resolution.txt"), build_rc=1)
    result = br.verify(str(tmp_path), _findings(), runner=runner)
    assert not result.build_passed
    assert result.failure_kind == br.DEPENDENCY_RESOLUTION
    assert "org.apache.commons:commons-text" in result.suspects


def test_parse_resolved_versions_single():
    m = br.parse_resolved_versions(_read("dependency-tree.txt"))
    assert m["io.netty:netty-handler"] == {"4.2.15.Final"}
    assert m["com.fasterxml.jackson.core:jackson-databind"] == {"2.15.4"}


def test_parse_resolved_versions_reactor_collects_across_modules():
    m = br.parse_resolved_versions(_read("dependency-tree-reactor.txt"))
    # jackson resolves differently in the two modules
    assert m["com.fasterxml.jackson.core:jackson-databind"] == {"2.15.4", "2.13.0"}
    assert m["io.netty:netty-handler"] == {"4.2.15.Final"}


def test_build_resolutions_ok_and_mismatch():
    resolved = {"io.netty:netty-handler": {"4.2.15.Final"},
                "com.fasterxml.jackson.core:jackson-databind": {"2.15.4", "2.13.0"}}
    res = {r.coordinate: r for r in br.build_resolutions(_findings(), resolved)}
    assert res["io.netty:netty-handler"].ok
    jackson = res["com.fasterxml.jackson.core:jackson-databind"]
    assert not jackson.ok and jackson.resolved == "2.13.0"  # offending module version


def test_build_resolutions_absent_is_mismatch():
    res = br.build_resolutions([Finding("io.netty:netty-handler", "4.2.4.Final", "4.2.15.Final")], {})
    assert not res[0].ok and res[0].resolved == ""


def test_verify_success(tmp_path):
    runner = _fake_runner(_read("build-success.txt"), 0, _read("dependency-tree.txt"))
    result = br.verify(str(tmp_path), _findings(), runner=runner)
    assert result.build_passed and result.success
    assert all(r.ok for r in result.resolutions)


def test_verify_green_but_unresolved(tmp_path):
    runner = _fake_runner(_read("build-success.txt"), 0, _read("dependency-tree-reactor.txt"))
    result = br.verify(str(tmp_path), _findings(), runner=runner)
    assert result.build_passed and not result.success
    assert any(not r.ok for r in result.resolutions)
    assert result.attempted  # likely culprits surfaced


def test_verify_build_failure_skips_tree(tmp_path):
    calls = []

    def runner(goals, cwd):
        calls.append(list(goals))
        return 1, _read("build-failure.txt")

    result = br.verify(str(tmp_path), _findings(), runner=runner)
    assert not result.build_passed and not result.success
    assert result.failing_goal == "compile"
    assert result.log_tail
    assert ["dependency:tree"] not in calls  # no resolution check after a failed build


def test_verify_maven_not_found(tmp_path):
    def runner(goals, cwd):
        raise FileNotFoundError("Maven not found")

    result = br.verify(str(tmp_path), _findings(), runner=runner)
    assert not result.build_passed and not result.success
    assert "Maven not found" in result.message
