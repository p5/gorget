"""Shared context for transform step handlers.

Unlike `fetch/base.py`'s `FetchStepHandler` (uniform `run(step, ctx) -> list[
FetchedArtifact]`), transform handlers take the shared `run(step, ctx, state) ->
None` shape and mutate `state` directly -- the primitives are genuinely
heterogeneous (strip-tarball replaces an existing artifact, vendor-bump touches
neither the artifact list nor produces one, run appends new artifacts),
so forcing a single return-based contract would fit worse than it would help.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry, TransformStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.pipeline.state import StageState
from gorget.util.archive import extract_tar_gz


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
    vendor, run). Reuses a `git` fetch step's checkout if one ran;
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
    return extract_dir
