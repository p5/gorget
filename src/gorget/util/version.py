"""Minimum-version comparison for vendor-bump/policy vendor-constraints.

Deliberately not a full semver implementation -- no pre-release ordering, no
build-metadata semantics. Good enough for "is this CVE-fix version present,"
which is all minimum-version gating actually needs.
"""

from __future__ import annotations


def _parse(version: str) -> tuple[int, ...]:
    version = version.lstrip("vV")  # Go module versions are always "vX.Y.Z"
    version = version.split("+", 1)[0]  # strip build metadata
    version = version.split("-", 1)[0]  # strip pre-release suffix
    return tuple(int(part) for part in version.split(".") if part.isdigit())


def meets_minimum(actual: str, minimum: str) -> bool:
    """True if `actual` >= `minimum`, compared component-wise numerically."""
    actual_parts = _parse(actual)
    minimum_parts = _parse(minimum)
    length = max(len(actual_parts), len(minimum_parts))
    actual_parts += (0,) * (length - len(actual_parts))
    minimum_parts += (0,) * (length - len(minimum_parts))
    return actual_parts >= minimum_parts


def matches_prefix(actual: str, prefix: str) -> bool:
    """True if `actual` starts with `prefix` component-wise.

    matches_prefix("4.18.2", "4.18") is True.
    matches_prefix("4.19.0", "4.18") is False.
    """
    actual_parts = _parse(actual)
    prefix_parts = _parse(prefix)
    return actual_parts[: len(prefix_parts)] == prefix_parts


def satisfies_constraint(actual: str, constraint: str) -> bool:
    """True if `actual` satisfies `constraint`.

    Plain version ("0.39.0") checks >= (minimum) with no upper bound.

    Tilde ("~4.18.2") is npm-style: a minimum floor *and* a same-series cap --
    `~x.y.z` and `~x.y` allow the `x.y` series (>= floor, < x.(y+1)); `~x`
    allows the `x` major (>= floor, < (x+1)). This matters for CVE fixes: it
    both enforces the patched floor (so an unpatched `4.18.0` is NOT satisfied
    by `~4.18.2`) and avoids floating across a major/minor boundary.
    """
    if constraint.startswith("~"):
        floor = constraint[1:]
        if not meets_minimum(actual, floor):
            return False
        floor_parts = _parse(floor)
        actual_parts = _parse(actual)
        # 1-component floor (~4) caps at the major; otherwise cap at the minor.
        series = 1 if len(floor_parts) == 1 else 2
        return actual_parts[:series] == floor_parts[:series]
    return meets_minimum(actual, constraint)
