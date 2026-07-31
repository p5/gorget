"""Shared interfaces for per-ecosystem vendor archive generation.

`VendorHandler`/`VendorEcosystem` are typed against `VendorRunContext` (a Protocol)
rather than the concrete `FetchContext` so the exact same vendor step/ecosystem code
can run from either the Fetch stage's `vendor` step or the Transform stage's `vendor`
step (reused there to let `vendor-bump` edit lockfiles before vendoring runs).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.config.substitution import SubstitutionVars


class VendorRunContext(Protocol):
    work_dir: Path
    vars: SubstitutionVars
    dry_run: bool
    source_dir: Path | None
    toolchain: list[ToolchainEntry]
    package_dir: Path


class VendorEcosystem(Protocol):
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        """Run the ecosystem's vendor command against `module_dir` and return the
        path to the produced vendor directory.

        `package_dir` is the RPM package directory (containing the spec,
        go-vendor-tools.toml, etc.) -- distinct from `module_dir`, the freshly
        fetched upstream checkout being vendored. Only the `go` ecosystem
        currently uses it (to read go-vendor-tools.toml); other ecosystems
        accept and ignore it.

        `use_workspace` is also go-specific: when `module_dir` has its own
        go.work, `False` forces GOWORK=off (isolated single-module vendor)
        instead of `go work vendor` (combined workspace vendor) -- e.g.
        prometheus deliberately excludes workspace members like
        compliance/internal/tools from its vendor archive.
        """
        ...
