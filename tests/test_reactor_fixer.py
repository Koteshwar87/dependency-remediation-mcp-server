"""Tests for reactor discovery + auto fix-targeting (no Maven; pure planning)."""
from __future__ import annotations
import os
import shutil
from pathlib import Path

from dep_remediation.core.advisory_parser import Finding
from dep_remediation.core import pom_fixer

REACTOR = Path(__file__).parent / "fixtures" / "poms" / "reactor"


def _findings():
    return [
        Finding("org.apache.commons:commons-text", "1.9", "1.10.0"),          # direct -> module-lib
        Finding("org.apache.commons:commons-collections4", "4.1", "4.4"),     # property -> module-lib
        Finding("io.netty:netty-handler", "", "4.2.15.Final"),                # managed -> aggregator pin
        Finding("com.fasterxml.jackson.core:jackson-databind", "", "2.15.4"), # transitive -> aggregator pin
    ]


def test_discover_reactor_finds_root_and_modules():
    poms = pom_fixer.discover_reactor(str(REACTOR / "pom.xml"))
    rels = sorted(os.path.relpath(p, REACTOR).replace("\\", "/") for p in poms)
    assert rels == ["module-app/pom.xml", "module-lib/pom.xml", "pom.xml"]


def test_routing_edits_in_module_pins_in_aggregator():
    result = pom_fixer.plan_remediation(str(REACTOR), _findings())
    # index actions by coordinate -> (pom basename dir, strategy)
    by_coord = {a["coordinate"]: a for a in result.to_dict()["actions"]}

    def where(coord):
        return os.path.basename(os.path.dirname(by_coord[coord]["pom_path"]))

    # direct + property edited in the module that declares them
    assert where("org.apache.commons:commons-text") == "module-lib"
    assert by_coord["org.apache.commons:commons-text"]["strategy"] == pom_fixer.EDIT_VERSION
    assert where("org.apache.commons:commons-collections4") == "module-lib"
    assert by_coord["org.apache.commons:commons-collections4"]["strategy"] == pom_fixer.EDIT_PROPERTY

    # managed + transitive pinned in the aggregator (reactor root dir)
    assert where("io.netty:netty-handler") == "reactor"
    assert by_coord["io.netty:netty-handler"]["strategy"] == pom_fixer.ADD_PIN
    assert where("com.fasterxml.jackson.core:jackson-databind") == "reactor"
    assert by_coord["com.fasterxml.jackson.core:jackson-databind"]["strategy"] == pom_fixer.ADD_PIN


def test_no_spurious_pins_in_non_declaring_module():
    result = pom_fixer.plan_remediation(str(REACTOR), _findings())
    app = next(r for r in result.results if r.pom_path.endswith(os.path.join("module-app", "pom.xml")))
    # module-app declares only netty (versionless) -> it must NOT get any pin of its own
    assert app.actions == []


def test_apply_writes_each_pom_to_its_right_place(tmp_path):
    dst = tmp_path / "reactor"
    shutil.copytree(REACTOR, dst)
    result = pom_fixer.apply_remediation(str(dst), _findings(), dry_run=False)
    assert result.applied

    lib = (dst / "module-lib" / "pom.xml").read_text(encoding="utf-8")
    assert "<version>1.10.0</version>" in lib                      # direct edited
    assert "<commons-collections4.version>4.4</commons-collections4.version>" in lib  # property edited

    root = (dst / "pom.xml").read_text(encoding="utf-8")
    assert "netty-handler" in root and "4.2.15.Final" in root     # pin in aggregator
    assert "jackson-databind" in root and "2.15.4" in root

    app = (dst / "module-app" / "pom.xml").read_text(encoding="utf-8")
    assert "dependencyManagement" not in app                      # no pin leaked into the module
