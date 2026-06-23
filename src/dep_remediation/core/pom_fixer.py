"""Pom fixer (Phase 3).

Takes the deduped findings from the advisory parser and applies the recommended
version upgrades to a single Spring Boot `pom.xml`. For each finding the engine first
**classifies how the coordinate resolves** in the pom, then either edits a version in
place or adds/updates a `<dependencyManagement>` pin.

Deterministic and LLM-free; no Maven invocation (that is Phase 4) and no network.
Operates on the single pom passed in (multi-module reactor traversal is Phase 2).

Trust rules (plan §7/§9): dry-run by default, idempotent, never downgrade, and a
resolution log plus a "needs manual review" bucket for anything not safely fixable.
"""
from __future__ import annotations
import difflib
import os
from dataclasses import dataclass, asdict, field

from lxml import etree

from .advisory_parser import Finding
from .version_compare import compare

# Resolution classes (how a coordinate's version is sourced in the pom).
DIRECT = "direct"          # <dependency> with a literal <version>
PROPERTY = "property"      # <version>${x}</version> backed by a <properties> entry
MANAGED = "managed"        # version owned by a parent / BOM, or a <dependencyManagement> entry
TRANSITIVE = "transitive"  # not declared in this pom at all
AMBIGUOUS = "ambiguous"    # version is an unresolvable property -> manual review

# Apply strategies.
EDIT_VERSION = "edit-version"
EDIT_PROPERTY = "edit-property"
ADD_PIN = "add-pin"
UPDATE_PIN = "update-pin"
SKIP_NOT_HIGHER = "skip-not-higher"

_PIN_COMMENT = " security pin "


@dataclass
class FixAction:
    coordinate: str
    resolution_class: str
    strategy: str
    from_version: str       # "" when not statically known (transitive / parent-managed)
    to_version: str
    detail: str = ""


@dataclass
class ManualReview:
    coordinate: str
    reason: str


@dataclass
class FixResult:
    pom_path: str
    actions: list[FixAction] = field(default_factory=list)
    manual_review: list[ManualReview] = field(default_factory=list)
    diff: str = ""
    applied: bool = False

    def to_dict(self):
        return asdict(self)


def _ns_qname(root) -> str:
    """Return the '{uri}' namespace prefix used by the pom, or '' if none."""
    uri = etree.QName(root).namespace
    return f"{{{uri}}}" if uri else ""


def _find_one(parent, q: str):
    return parent.find(q) if parent is not None else None


def _text(el) -> str:
    return el.text.strip() if el is not None and el.text else ""


def _indent_unit(root) -> str:
    """Infer the indentation unit (whitespace before the first top-level child)."""
    if root.text and "\n" in root.text:
        ws = root.text.rsplit("\n", 1)[-1]
        if ws and ws.strip() == "":
            return ws
    return "    "


def _depth(el) -> int:
    return sum(1 for _ in el.iterancestors())


def _append_pretty(container, new_el, indent_unit: str):
    """Append new_el to container with indentation matching the document."""
    depth = _depth(container)
    container_indent = indent_unit * depth
    child_indent = indent_unit * (depth + 1)
    existing = list(container)
    container.append(new_el)
    if existing:
        existing[-1].tail = "\n" + child_indent
    else:
        container.text = "\n" + child_indent
    new_el.tail = "\n" + container_indent
    # indent new_el's own descendants relative to its depth
    etree.indent(new_el, space=indent_unit, level=depth + 1)


def _dependencies_of(parent, q: str):
    """Yield <dependency> elements that are direct grandchildren via <dependencies>."""
    deps = _find_one(parent, f"{q}dependencies")
    return list(deps) if deps is not None else []


def _match(dep, q: str, group: str, artifact: str) -> bool:
    return (_text(_find_one(dep, f"{q}groupId")) == group
            and _text(_find_one(dep, f"{q}artifactId")) == artifact)


def _classify(root, q: str, coordinate: str):
    """Classify a coordinate. Returns (resolution_class, version_el, prop_el).

    version_el / prop_el point at the element whose text should be edited (or None
    when a new <dependencyManagement> pin must be created).
    """
    group, _, artifact = coordinate.partition(":")
    dep_mgmt = _find_one(root, f"{q}dependencyManagement")
    properties = _find_one(root, f"{q}properties")

    # 1) direct dependency (under <project>/<dependencies>, not dependencyManagement)
    for dep in _dependencies_of(root, q):
        if _match(dep, q, group, artifact):
            ver = _find_one(dep, f"{q}version")
            vtext = _text(ver)
            if not vtext:
                break  # declared but version managed elsewhere -> treat as managed
            if vtext.startswith("${") and vtext.endswith("}"):
                pname = vtext[2:-1]
                pel = _find_one(properties, f"{q}{pname}") if properties is not None else None
                if pel is not None:
                    return PROPERTY, None, pel
                return AMBIGUOUS, None, None
            return DIRECT, ver, None

    # 2) managed via a local <dependencyManagement> entry with a literal version
    for dep in _dependencies_of(dep_mgmt, q):
        if _match(dep, q, group, artifact):
            ver = _find_one(dep, f"{q}version")
            if _text(ver):
                return MANAGED, ver, None
            return MANAGED, None, None  # entry exists but no literal version

    # 3) referenced as a versionless direct dep (parent/BOM-managed) -> managed pin
    for dep in _dependencies_of(root, q):
        if _match(dep, q, group, artifact):
            return MANAGED, None, None

    # 4) not in the pom at all -> transitive (still fixable via a pin)
    return TRANSITIVE, None, None


def _ensure_dep_mgmt_container(root, q: str, indent_unit: str):
    """Return the <dependencyManagement>/<dependencies> element, creating it if absent."""
    dep_mgmt = _find_one(root, f"{q}dependencyManagement")
    if dep_mgmt is None:
        dep_mgmt = etree.SubElement(root, f"{q}dependencyManagement")
        # move it out of SubElement's default placement into a pretty append
        root.remove(dep_mgmt)
        _append_pretty(root, dep_mgmt, indent_unit)
    deps = _find_one(dep_mgmt, f"{q}dependencies")
    if deps is None:
        deps = etree.SubElement(dep_mgmt, f"{q}dependencies")
        dep_mgmt.remove(deps)
        _append_pretty(dep_mgmt, deps, indent_unit)
    return deps


def _add_pin(root, q: str, coordinate: str, version: str, indent_unit: str):
    group, _, artifact = coordinate.partition(":")
    deps = _ensure_dep_mgmt_container(root, q, indent_unit)
    dep = etree.Element(f"{q}dependency")
    etree.SubElement(dep, f"{q}groupId").text = group
    etree.SubElement(dep, f"{q}artifactId").text = artifact
    etree.SubElement(dep, f"{q}version").text = version
    _append_pretty(deps, dep, indent_unit)
    comment = etree.Comment(_PIN_COMMENT)
    dep.addprevious(comment)
    comment.tail = "\n" + indent_unit * _depth(dep)  # keep <dependency> on its own line


def plan_fixes(pom_path: str, findings: list[Finding], *, pin_unmatched: bool = True) -> FixResult:
    """Classify and compute fixes for `findings` against `pom_path` (no write).

    `pin_unmatched` controls what happens to a finding this pom does not declare with a
    fixable version (managed-versionless / transitive). Default True adds a
    `<dependencyManagement>` pin here. Set False during a reactor per-module pass so a
    module only gets edits for what it actually declares; the unmatched findings are then
    routed to the aggregator by `apply_remediation`.
    """
    parser = etree.XMLParser(remove_blank_text=False)
    tree = etree.parse(pom_path, parser)
    root = tree.getroot()
    q = _ns_qname(root)
    indent_unit = _indent_unit(root)

    before = etree.tostring(tree, encoding="unicode")
    result = FixResult(pom_path=pom_path)

    for f in findings:
        rclass, ver_el, prop_el = _classify(root, q, f.coordinate)
        target = ver_el if ver_el is not None else prop_el

        if rclass == AMBIGUOUS:
            result.manual_review.append(ManualReview(
                f.coordinate, "version is an unresolvable property; needs manual review"))
            continue

        # edit-in-place cases have a current literal version -> enforce no-downgrade
        if target is not None:
            current = _text(target)
            if current and compare(current, f.recommended_version) >= 0:
                result.actions.append(FixAction(
                    f.coordinate, rclass, SKIP_NOT_HIGHER, current,
                    f.recommended_version, "existing version already >= recommended"))
                continue
            target.text = f.recommended_version
            strategy = (EDIT_PROPERTY if prop_el is not None
                        else EDIT_VERSION if rclass == DIRECT else UPDATE_PIN)
            result.actions.append(FixAction(
                f.coordinate, rclass, strategy, current, f.recommended_version))
            continue

        # managed-by-parent or transitive -> add a dependencyManagement pin (unless this is
        # a reactor per-module pass, where unmatched findings are routed to the aggregator)
        if not pin_unmatched:
            continue
        _add_pin(root, q, f.coordinate, f.recommended_version, indent_unit)
        result.actions.append(FixAction(
            f.coordinate, rclass, ADD_PIN, "", f.recommended_version,
            "added <dependencyManagement> pin"))

    after = etree.tostring(tree, encoding="unicode")
    result.diff = "".join(difflib.unified_diff(
        before.splitlines(keepends=True), after.splitlines(keepends=True),
        fromfile=f"{pom_path} (before)", tofile=f"{pom_path} (after)"))
    # stash the serialized result for apply_fixes to write
    result._after = after  # type: ignore[attr-defined]
    return result


def apply_fixes(pom_path: str, findings: list[Finding], *, dry_run: bool = True,
                pin_unmatched: bool = True) -> FixResult:
    """Plan fixes and, unless dry_run, write the modified pom back to disk."""
    result = plan_fixes(pom_path, findings, pin_unmatched=pin_unmatched)
    changed = any(a.strategy != SKIP_NOT_HIGHER for a in result.actions)
    if not dry_run and changed:
        with open(pom_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(result._after)  # type: ignore[attr-defined]
        result.applied = True
    return result


# --------------------------------------------------------------------------------------
# Reactor (multi-module) auto fix-targeting
# --------------------------------------------------------------------------------------

@dataclass
class ReactorFixResult:
    """Aggregates per-pom FixResults for a (possibly single-module) project. root pom first."""
    root: str
    results: list[FixResult] = field(default_factory=list)

    @property
    def applied(self) -> bool:
        return any(r.applied for r in self.results)

    def to_dict(self):
        actions, manual, diffs = [], [], []
        for r in self.results:
            for a in r.actions:
                d = asdict(a); d["pom_path"] = r.pom_path; actions.append(d)
            for m in r.manual_review:
                d = asdict(m); d["pom_path"] = r.pom_path; manual.append(d)
            if r.diff:
                diffs.append(r.diff)
        return {"root": self.root, "applied": self.applied, "actions": actions,
                "manual_review": manual, "diff": "\n".join(diffs),
                "poms": [r.to_dict() for r in self.results]}


def _resolve_root_pom(target: str) -> str:
    """Accept a project dir or a pom path; return the pom path to start from."""
    return os.path.join(target, "pom.xml") if os.path.isdir(target) else target


def _module_poms(pom_path: str, q: str, root) -> list[str]:
    """Pom paths for the <modules> of an aggregator pom (each <module> is a directory)."""
    modules = _find_one(root, f"{q}modules")
    if modules is None:
        return []
    base = os.path.dirname(os.path.abspath(pom_path))
    out = []
    for m in modules.findall(f"{q}module"):
        name = (m.text or "").strip()
        if name:
            out.append(os.path.join(base, name, "pom.xml"))
    return out


def discover_reactor(root_pom: str) -> list[str]:
    """All pom paths in the reactor rooted at `root_pom` (root first), recursing into
    nested aggregators. A non-aggregator pom yields a 1-element list."""
    parser = etree.XMLParser(remove_blank_text=False)
    poms = [root_pom]
    tree = etree.parse(root_pom, parser)
    root = tree.getroot()
    q = _ns_qname(root)
    for child_pom in _module_poms(root_pom, q, root):
        if os.path.isfile(child_pom):
            poms.extend(discover_reactor(child_pom))
    return poms


def apply_remediation(target: str, findings: list[Finding], *, dry_run: bool = True) -> ReactorFixResult:
    """Auto-target findings across a (possibly multi-module) project and apply.

    `target` may be a project dir or a pom. For a reactor, each finding declared with a
    fixable version in a module is edited there; findings declared with a fixable version in
    no module (managed-versionless / transitive) are pinned once in the aggregator, inherited
    by all modules. A single-module pom keeps the original edit-or-pin-here behavior.
    """
    root_pom = _resolve_root_pom(target)
    poms = discover_reactor(root_pom)

    if len(poms) == 1:
        return ReactorFixResult(root_pom, [apply_fixes(root_pom, findings, dry_run=dry_run)])

    # per-module pass: edits only (no pinning); track what each module handled
    handled: set[str] = set()
    module_results = []
    for pom in poms[1:]:
        res = apply_fixes(pom, findings, dry_run=dry_run, pin_unmatched=False)
        module_results.append(res)
        handled.update(a.coordinate for a in res.actions)
        handled.update(m.coordinate for m in res.manual_review)

    # everything not handled by a module -> edit-or-pin at the aggregator root
    remaining = [f for f in findings if f.coordinate not in handled]
    root_res = apply_fixes(root_pom, remaining, dry_run=dry_run, pin_unmatched=True)
    return ReactorFixResult(root_pom, [root_res] + module_results)


def plan_remediation(target: str, findings: list[Finding]) -> ReactorFixResult:
    """Dry-run alias of apply_remediation (computes the cross-pom plan, writes nothing)."""
    return apply_remediation(target, findings, dry_run=True)


def print_reactor_result(result: ReactorFixResult):
    multi = len(result.results) > 1
    if multi:
        print(f"Reactor: {result.root}  ({len(result.results)} poms)\n")
    for i, r in enumerate(result.results):
        if multi and i:
            print()
        print_result(r)
    print(f"\nApplied (any pom): {result.applied}")


def print_result(result: FixResult):
    print(f"Pom: {result.pom_path}")
    print(f"Actions: {len(result.actions)}")
    for a in result.actions:
        frm = a.from_version or "(managed/transitive)"
        print(f"  [{a.resolution_class}/{a.strategy}] {a.coordinate}: {frm} -> {a.to_version}"
              + (f"  ({a.detail})" if a.detail else ""))
    if result.manual_review:
        print(f"\nNeeds manual review: {len(result.manual_review)}")
        for m in result.manual_review:
            print(f"  {m.coordinate}: {m.reason}")
    if result.diff:
        print("\n--- diff ---")
        print(result.diff, end="")
    else:
        print("\n(no changes)")
    print(f"\nApplied: {result.applied}")
