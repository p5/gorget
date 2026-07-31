"""Minimum-version comparison for vendor-bump/policy vendor-constraints.

Deliberately not a full semver implementation -- no pre-release ordering, no
build-metadata semantics. Good enough for "is this CVE-fix version present,"
which is all minimum-version gating actually needs.
"""

from __future__ import annotations

import re


def rpm_version(version: str) -> str:
    """Convert an npm/semver string to an RPM-compatible version.

    RPM has no '-' in versions and treats it as the version/release separator,
    so a semver pre-release (`1.2.3-rc.1`) becomes `1.2.3~rc.1` -- the `~`
    sorting lower than the base release, matching semver's "pre-release < release".
    Semver build metadata (`+build`) carries no version-ordering meaning, so it
    is dropped. Runs of `._~` are collapsed so the result stays a legal RPM
    version.
    """
    version = version.split("+", 1)[0]  # drop semver build metadata
    base, separator, prerelease = version.partition("-")
    if separator:
        prerelease = prerelease.lstrip("-._~").replace("-", ".")
        version = base + "~" + prerelease
    return re.sub(r"([._~])\1+", r"\1", version)


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
