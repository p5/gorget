"""Toolchain version validation for installed package build tools.

Gorget never fetches or switches toolchain versions -- it only checks that
whatever is *already installed* satisfies the pipeline's declared requirement,
failing fast (before any stage runs) if it doesn't. This is deliberately the
narrowest thing that can be useful: no network access, no external version
manager, no multi-version switching mechanism -- just a safety check against
the ambient environment.

A previous design shelled out to `mise` (https://mise.jdx.dev/) to actually
*activate* a specific version. That was rejected (see HUM-4990): mise's job is
downloading toolchain binaries directly from their own upstream release
channels at runtime, exactly the kind of untrusted-source problem Gorget
exists to eliminate for source tarballs, just one layer up. A real
multi-version mechanism needs to be RPM-native with zero mid-pipeline network
dependency (e.g. distinctly-named versioned binaries, the same pattern Fedora
already uses for python3.9/python3.11/python3.12) -- the exact convention is
still being decided (HUM-4990/HUM-4789). Until then, this module only
validates; it never selects between multiple installed versions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError
from gorget.util.subprocess_run import run

# name -> (version-check argv, regex whose group(1) captures the version).
_VERSION_CHECKS: dict[str, tuple[list[str], re.Pattern[str]]] = {
    "go": (["go", "version"], re.compile(r"go(\d+\.\d+(?:\.\d+)?)")),
    "node": (["node", "--version"], re.compile(r"v?(\d+\.\d+\.\d+)")),
    "npm": (["npm", "--version"], re.compile(r"(\d+\.\d+\.\d+)")),
    "cargo": (["cargo", "--version"], re.compile(r"cargo (\d+\.\d+\.\d+)")),
    "rustc": (["rustc", "--version"], re.compile(r"rustc (\d+\.\d+\.\d+)")),
    "python": (["python3", "--version"], re.compile(r"Python (\d+\.\d+\.\d+)")),
    "maven": (["mvn", "--version"], re.compile(r"Apache Maven (\d+\.\d+\.\d+)")),
}


def _version_matches(declared: str, active: str) -> bool:
    """Component-wise prefix match: "1.22" matches "1.22.3" but not "1.223"
    or "1.2". Plain string prefixing would incorrectly match the latter two.
    """
    declared_parts = declared.split(".")
    active_parts = active.split(".")
    return declared_parts == active_parts[: len(declared_parts)]


def verify_installed(entries: Sequence[ToolchainEntry]) -> None:
    for entry in entries:
        check = _VERSION_CHECKS.get(entry.name)
        if check is None:
            raise GorgetConfigError(
                f"Unknown toolchain name: {entry.name!r} (supported: "
                f"{sorted(_VERSION_CHECKS)}). gorget only validates an "
                f"already-installed version -- it doesn't fetch or switch "
                f"toolchain versions (see HUM-4990/HUM-4789)."
            )
        cmd, pattern = check
        try:
            result = run(cmd)
        except FileNotFoundError as exc:
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} is not available "
                f"(command not found: {cmd[0]!r})"
            ) from exc
        if result.returncode != 0:
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} is not available "
                f"({' '.join(cmd)} failed: {(result.stderr or result.stdout).strip()})"
            )

        output = result.stdout + result.stderr
        match = pattern.search(output)
        if not match:
            raise GorgetConfigError(
                f"Could not parse a version for {entry.name!r} from `{' '.join(cmd)}` "
                f"output: {output.strip()!r}"
            )

        active_version = match.group(1)
        if not _version_matches(entry.version, active_version):
            raise GorgetConfigError(
                f"Required toolchain {entry.name}@{entry.version} does not match the "
                f"installed version ({active_version}). gorget validates against "
                f"whatever is already installed -- it doesn't fetch or switch "
                f"toolchain versions (see HUM-4990/HUM-4789)."
            )


def wrap_command(cmd: list[str], entries: Sequence[ToolchainEntry]) -> list[str]:
    # No-op: there is no version-switching mechanism (see module docstring).
    # Kept as a real seam so the eventual RPM-native mechanism drops in here
    # without touching any of its call sites in fetch/vendor/*.py or
    # transform/*.py.
    return cmd
