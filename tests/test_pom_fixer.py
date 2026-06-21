"""Focused tests for the Phase 3 pom fixer.

Cover the four resolution classes, the no-downgrade guard, dependencyManagement-block
creation, and idempotency. XML surgery is unsafe to ship unverified, so these assert the
actual resulting pom content.
"""
from __future__ import annotations
import shutil
from pathlib import Path

from lxml import etree

from dep_remediation.core.advisory_parser import Finding
from dep_remediation.core import pom_fixer as pf

POMS = Path(__file__).parent / "fixtures" / "poms"
NETTY = "io.netty:netty-handler"


def _finding(coord="io.netty:netty-handler", cur="4.2.4.Final", rec="4.2.15.Final"):
    return Finding(coordinate=coord, current_version=cur, recommended_version=rec)


def _versions_in(xml_text, group, artifact):
    """Return the <version> texts for a given coordinate anywhere in the pom."""
    root = etree.fromstring(xml_text.encode())
    q = pf._ns_qname(root)
    out = []
    for dep in root.iter(f"{q}dependency"):
        if (pf._text(dep.find(f"{q}groupId")) == group
                and pf._text(dep.find(f"{q}artifactId")) == artifact):
            v = dep.find(f"{q}version")
            if v is not None and v.text:
                out.append(v.text.strip())
    return out


def test_direct_edit():
    res = pf.plan_fixes(str(POMS / "direct.xml"), [_finding()])
    assert len(res.actions) == 1
    a = res.actions[0]
    assert a.resolution_class == pf.DIRECT
    assert a.strategy == pf.EDIT_VERSION
    assert a.to_version == "4.2.15.Final"
    assert "4.2.15.Final" in res.diff and "4.2.4.Final" in res.diff


def test_no_downgrade():
    # recommended is LOWER than what's already in the pom -> skip
    res = pf.plan_fixes(str(POMS / "direct.xml"),
                        [_finding(rec="4.2.0.Final")])
    assert res.actions[0].strategy == pf.SKIP_NOT_HIGHER
    assert res.diff == ""


def test_property_edit():
    res = pf.plan_fixes(str(POMS / "property.xml"), [_finding()])
    a = res.actions[0]
    assert a.resolution_class == pf.PROPERTY
    assert a.strategy == pf.EDIT_PROPERTY
    assert "<netty.version>4.2.15.Final</netty.version>" in res._after


def test_managed_parent_adds_pin():
    res = pf.plan_fixes(str(POMS / "managed-parent.xml"), [_finding()])
    a = res.actions[0]
    assert a.resolution_class == pf.MANAGED
    assert a.strategy == pf.ADD_PIN
    assert "4.2.15.Final" in _versions_in(res._after, "io.netty", "netty-handler")
    assert "<dependencyManagement>" in res._after


def test_transitive_creates_dep_mgmt_block():
    res = pf.plan_fixes(str(POMS / "transitive.xml"), [_finding()])
    a = res.actions[0]
    assert a.resolution_class == pf.TRANSITIVE
    assert a.strategy == pf.ADD_PIN
    assert "<dependencyManagement>" in res._after
    assert "4.2.15.Final" in _versions_in(res._after, "io.netty", "netty-handler")
    # the produced pom must still be valid XML
    etree.fromstring(res._after.encode())


def test_idempotent_apply(tmp_path):
    for name in ("direct.xml", "property.xml", "managed-parent.xml", "transitive.xml"):
        target = tmp_path / name
        shutil.copy(POMS / name, target)
        first = pf.apply_fixes(str(target), [_finding()], dry_run=False)
        assert first.applied
        # second run must be a no-op (empty diff, nothing but skips)
        second = pf.apply_fixes(str(target), [_finding()], dry_run=False)
        assert second.diff == ""
        assert not second.applied
        assert all(x.strategy == pf.SKIP_NOT_HIGHER for x in second.actions)


def test_ambiguous_unresolvable_property(tmp_path):
    # version is ${missing.prop} with no <properties> entry -> manual review
    pom = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        '    <dependencies>\n'
        '        <dependency>\n'
        '            <groupId>io.netty</groupId>\n'
        '            <artifactId>netty-handler</artifactId>\n'
        '            <version>${missing.prop}</version>\n'
        '        </dependency>\n'
        '    </dependencies>\n'
        '</project>\n'
    )
    path = tmp_path / "ambiguous.xml"
    path.write_text(pom, encoding="utf-8")
    res = pf.plan_fixes(str(path), [_finding()])
    assert not res.actions
    assert res.manual_review and res.manual_review[0].coordinate == NETTY
