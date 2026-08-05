"""Shared context for transform step handlers.

Unlike `fetch/base.py`'s `FetchStepHandler` (uniform `run(step, ctx) -> list[
FetchedArtifact]`), transform handlers take the shared `run(step, ctx, state) ->
None` shape and mutate `state` directly -- the primitives are genuinely
heterogeneous (strip-tarball replaces an existing artifact, vendor-bump touches
neither the artifact list nor produces one, build-ui/run append new artifacts),
so forcing a single return-based contract would fit worse than it would help.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry, TransformStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import build_artifact
from gorget.pipeline.state import StageState
from gorget.util.archive import extract_tar_gz, make_tar_gz, repack_tar_gz, strip_archive_suffix
from gorget.util.git import commit_timestamp


@dataclass(kw_only=True)
class TransformContext:
    work_dir: Path
    source_dir: Path | None
    vars: SubstitutionVars
    toolchain: list[ToolchainEntry]
    dry_run: bool
    package_dir: Path


class TransformStepHandler(Protocol):
    def run(self, step: TransformStep, ctx: TransformContext, state: StageState) -> None: ...


def ensure_source_dir(ctx: TransformContext, state: StageState, target: str | None = None) -> Path:
    """Return the working source tree for steps that need one (vendor-bump,
    vendor, build-ui, run). Reuses a `git` fetch step's checkout if one ran;
    otherwise extracts the sole fetched artifact, since there's no other way to
    guess which one to use if there's more than one (or none).

    `target`, when given, names a specific fetched artifact to extract instead
    -- required as soon as a pipeline fetches more than one artifact, since the
    "exactly one" guess no longer applies. Extracted into its own target-keyed
    scratch dir and returned directly, deliberately *not* cached into
    `ctx.source_dir`, so an explicit `target` on one step can never leak into
    a later step's implicit default.
    """
    if target is not None:
        artifact = state.find_artifact(target)
        extract_dir = ctx.work_dir / "_transform_source" / target
        extract_tar_gz(artifact.path, extract_dir)
        return extract_dir
    if ctx.source_dir is not None:
        return ctx.source_dir
    if len(state.artifacts) != 1:
        raise GorgetConfigError(
            "This transform step needs a source checkout, but no 'git' fetch step "
            "ran and there isn't exactly one fetched artifact to extract instead "
            f"(found {len(state.artifacts)})"
        )
    extract_dir = ctx.work_dir / "_transform_source"
    extract_tar_gz(state.artifacts[0].path, extract_dir)
    ctx.source_dir = extract_dir
    # Back the shared source tree with the artifact we extracted, so an in-place
    # edit can be repacked into it at stage end. The extracted tree already
    # carries the tarball's internal top-level dir, so it repacks as-is.
    state.source_artifact = state.artifacts[0]
    state.source_is_checkout = False
    return extract_dir


def finalize_source_artifact(state: StageState, *, dry_run: bool) -> None:
    """Repack the shared source tarball once, if a transform step edited the
    working tree in place (`state.source_dirty`).

    Keeps the shipped source tarball consistent with the tree that later steps
    (e.g. `vendor`) built against -- without every mutating step having to know
    about artifacts or re-archiving. A bare git checkout is re-wrapped under the
    tarball's original top-level dir (via `make_tar_gz`'s `arcname`, stamped with
    the commit timestamp so the bytes stay deterministic); an extracted tree
    already carries that dir and is repacked as-is.
    """
    if dry_run or not state.source_dirty:
        return
    artifact = state.source_artifact
    if artifact is None or state.source_dir is None:
        return
    if state.source_is_checkout:
        make_tar_gz(
            state.source_dir,
            artifact.path,
            arcname=strip_archive_suffix(artifact.output_name),
            mtime=commit_timestamp(state.source_dir),
        )
    else:
        repack_tar_gz(state.source_dir, artifact.path)
    # FetchedArtifact is frozen and its checksum changed, so replace it in place.
    for index, existing in enumerate(state.artifacts):
        if existing.output_name == artifact.output_name:
            rebuilt = build_artifact(
                artifact.path, artifact.output_name, existing.source_description, dry_run=False
            )
            state.artifacts[index] = rebuilt
            state.source_artifact = rebuilt
            break
    state.source_dirty = False
