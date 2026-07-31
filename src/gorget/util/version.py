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
