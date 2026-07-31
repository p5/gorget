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

    Plain version ("0.39.0") checks >= (minimum).
    Tilde-prefixed ("~4.18") checks prefix match.
    """
    if constraint.startswith("~"):
        return matches_prefix(actual, constraint[1:])
    return meets_minimum(actual, constraint)
