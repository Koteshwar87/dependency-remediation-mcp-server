"""Tests for the recovery-loop curated re-apply primitive (apply_overrides)."""
from __future__ import annotations

from dep_remediation.core.advisory_parser import Finding, apply_overrides


def _findings():
    return [
        Finding("org.apache.commons:commons-text", "1.9", "1.10.0"),
        Finding("org.yaml:snakeyaml", "2.2", "2.3"),
    ]


def test_no_overrides_returns_equivalent_list():
    out = apply_overrides(_findings(), {})
    assert [f.recommended_version for f in out] == ["1.10.0", "2.3"]


def test_override_retargets_version():
    out = apply_overrides(_findings(), {"org.apache.commons:commons-text": "1.11.0"})
    by = {f.coordinate: f for f in out}
    assert by["org.apache.commons:commons-text"].recommended_version == "1.11.0"
    assert by["org.yaml:snakeyaml"].recommended_version == "2.3"  # untouched


def test_skip_drops_finding():
    out = apply_overrides(_findings(), {"org.apache.commons:commons-text": ""})
    assert [f.coordinate for f in out] == ["org.yaml:snakeyaml"]


def test_unknown_coordinate_ignored_and_input_not_mutated():
    findings = _findings()
    out = apply_overrides(findings, {"com.example:absent": "9.9"})
    assert [f.coordinate for f in out] == [f.coordinate for f in findings]
    assert findings[0].recommended_version == "1.10.0"  # original untouched


def test_none_overrides_is_safe():
    out = apply_overrides(_findings(), None)
    assert len(out) == 2
