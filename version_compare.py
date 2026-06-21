"""Maven-aware version comparison.

Implements a practical subset of Maven's version-ordering rules so that, e.g.,
4.2.15.Final > 4.2.4.Final and 2.15.4 > 2.13.0 (string sort gets these wrong).

Reference: Maven ComparableVersion semantics (qualifiers, numeric vs string items).
This is a pragmatic implementation covering the cases real advisory data shows:
dotted numeric versions with optional trailing qualifiers (Final, RELEASE,
Alpha/Beta/RC/SNAPSHOT, etc.).
"""
from __future__ import annotations
import re
from functools import cmp_to_key

# Known qualifiers ordered from oldest -> newest. "" (release) and "final"/"ga"
# are treated as the baseline release. Anything unknown sorts as a string item.
_QUALIFIER_ORDER = {
    "alpha": -5, "a": -5,
    "beta": -4, "b": -4,
    "milestone": -3, "m": -3,
    "rc": -2, "cr": -2,
    "snapshot": -1,
    "": 0, "final": 0, "ga": 0, "release": 0,
    "sp": 1,
}


def _split_items(version: str):
    """Split a version string into comparable items.

    Separators are '.', '-', '_', and transitions between digit and letter.
    Each item is either an int (numeric) or a lowercased string (qualifier).
    """
    v = version.strip().lower()
    # normalize separators to '.'
    v = re.sub(r"[-_]", ".", v)
    # insert a '.' between letter/number transitions: 4final -> 4.final
    v = re.sub(r"(\d)([a-z])", r"\1.\2", v)
    v = re.sub(r"([a-z])(\d)", r"\1.\2", v)
    items = []
    for part in v.split("."):
        if part == "":
            continue
        if part.isdigit():
            items.append(int(part))
        else:
            items.append(part)
    return items


def _cmp_item(a, b):
    a_num, b_num = isinstance(a, int), isinstance(b, int)
    if a_num and b_num:
        return (a > b) - (a < b)
    if a_num and not b_num:
        # numeric item sorts higher than a qualifier string (1.0 > 1.0.alpha)
        return 1
    if b_num and not a_num:
        return -1
    # both strings -> qualifier ordering, unknown qualifiers compared lexically
    ra = _QUALIFIER_ORDER.get(a)
    rb = _QUALIFIER_ORDER.get(b)
    if ra is not None and rb is not None:
        return (ra > rb) - (ra < rb)
    if ra is not None and rb is None:
        return 1
    if rb is not None and ra is None:
        return -1
    return (a > b) - (a < b)


def compare(v1: str, v2: str) -> int:
    """Return -1 if v1<v2, 0 if equal, 1 if v1>v2 (Maven-aware)."""
    i1, i2 = _split_items(v1), _split_items(v2)
    for a, b in zip(i1, i2):
        c = _cmp_item(a, b)
        if c != 0:
            return c
    # longer version is greater only if the extra items are "positive"
    if len(i1) == len(i2):
        return 0
    longer, sign = (i1, 1) if len(i1) > len(i2) else (i2, -1)
    for extra in longer[min(len(i1), len(i2)):]:
        if isinstance(extra, int):
            if extra != 0:
                return sign
        else:
            r = _QUALIFIER_ORDER.get(extra, 0)
            if r < 0:
                return -sign  # e.g. 1.0-alpha < 1.0
            if r > 0:
                return sign
    return 0


version_key = cmp_to_key(compare)


def max_version(versions):
    """Return the highest version from an iterable using Maven ordering."""
    versions = list(versions)
    if not versions:
        return None
    best = versions[0]
    for v in versions[1:]:
        if compare(v, best) > 0:
            best = v
    return best


if __name__ == "__main__":
    tests = [
        ("4.2.15.Final", "4.2.4.Final", 1),
        ("2.15.4", "2.13.0", 1),
        ("6.2.11", "6.2.11", 0),
        ("4.2.13.Final", "4.2.15.Final", -1),
        ("1.0.0", "1.0.0.RELEASE", 0),
        ("1.0.0", "1.0.0-alpha1", 1),
        ("2.17.1", "2.14.0", 1),
    ]
    ok = True
    for a, b, want in tests:
        got = compare(a, b)
        flag = "OK" if got == want else "FAIL"
        if got != want:
            ok = False
        print(f"[{flag}] compare({a!r}, {b!r}) = {got} (want {want})")
    print("ALL PASS" if ok else "SOME FAILED")
