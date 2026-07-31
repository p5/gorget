"""Shared guardrail for gorget's `fetch: {git}` + Go vendoring architecture: a
`git` fetch step archives `Source0` from the checkout *before* anything else
gets a chance to mutate it, so any later step that rewrites `go.mod`/`go.sum`
in that same checkout -- `go-vendor-tools.toml`'s `pre_commands`/
`dependency_overrides` (see `fetch/vendor/go.py`), or a `transform: vendor-bump`
step (see `transform/vendor_bump.py`) -- only affects the vendor archive, never
the plain source tarball. Without an equivalent spec patch, the actual build
tree (Source0 + patches) and the generated vendor archive end up requiring
different versions of the same dependency, which `go build -mod=vendor`
rejects as inconsistent vendoring.

This is not hypothetical: it silently broke trivy. Two CVE-backport commits
added `go get` pre_commands to bump vendored dependencies without a matching
spec patch, and the mismatch sat latent for over a week until an unrelated
version bump's %check run finally caught it.
"""

from __future__ import annotations

import re
from pathlib import Path

from gorget.exceptions import GorgetConfigError
from gorget.specfile import SpecFile

_DIFF_TARGET_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_GOMOD_FILENAMES = frozenset({"go.mod", "go.sum"})


def patch_touches_gomod(patch_path: Path) -> bool:
    if not patch_path.is_file():
        return False
    text = patch_path.read_text(errors="replace")
    targets = {Path(p).name for p in _DIFF_TARGET_RE.findall(text)}
    return bool(targets & _GOMOD_FILENAMES)


def find_spec_path(package_dir: Path) -> Path | None:
    spec_files = sorted(package_dir.glob("*.spec"))
    return spec_files[0] if len(spec_files) == 1 else None


def raise_unless_spec_patches_gomod(package_dir: Path, *, reason: str) -> None:
    """Raise `GorgetConfigError` unless at least one of `package_dir`'s spec-declared
    patches touches go.mod/go.sum. `reason` describes what just mutated go.mod/go.sum
    in the checkout, for the error message.

    Silently returns (skips validation) if `package_dir` has no unambiguous spec file
    -- a malformed package layout isn't this check's job to report; whatever reads the
    spec next will fail with a clearer, more specific error.
    """
    spec_path = find_spec_path(package_dir)
    if spec_path is None:
        return

    patches = SpecFile(spec_path, sourcedir=package_dir).patches()
    if any(patch_touches_gomod(package_dir / patch.filename) for patch in patches):
        return

    raise GorgetConfigError(
        f"{reason}, but none of {spec_path.name}'s Patches touch go.mod or go.sum.\n\n"
        f"That mutation only ever applies to this vendor-archive checkout -- the plain "
        f"source tarball (Source0) never sees it, so go.mod in the actual %prep/%build "
        f"tree can require different versions than vendor/modules.txt in the generated "
        f"vendor archive, which `go build -mod=vendor` rejects as inconsistent vendoring. "
        f"Add a PatchN to {spec_path.name} that applies the same go.mod/go.sum change, "
        f"computed offline (Konflux builds are hermetic -- %prep has no network access "
        f"to re-run `go get`/`go mod tidy` itself)."
    )
