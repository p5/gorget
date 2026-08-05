"""Mutable state threaded through the stage pipeline (fetch's artifacts feed emit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact
from gorget.pipeline.result import PipelineReport
from gorget.specfile import SpecFile


@dataclass(kw_only=True)
class StageState:
    work_dir: Path
    spec: SpecFile
    report: PipelineReport
    artifacts: list[FetchedArtifact] = field(default_factory=list)
    # Set by FetchStage after a `git` step clones a checkout, so Transform can
    # reuse it (e.g. for `vendor-bump`/`vendor`/`build-ui`/`run` steps) without
    # re-extracting a tarball.
    source_dir: Path | None = None
    # The fetched artifact whose bytes correspond to `source_dir` -- the git
    # source tarball, or the sole artifact extracted for transforms. When a
    # transform step edits the shared source tree in place (e.g. vendor-bump
    # bumping a lockfile), TransformStage repacks this artifact once at the end
    # so the shipped source tarball matches what later steps (e.g. `vendor`)
    # built against.
    source_artifact: FetchedArtifact | None = None
    # True when `source_dir` is a bare git checkout (files at its root, so a
    # repack must re-wrap them under the tarball's internal top-level dir);
    # False when it's an extracted tarball tree (that wrapper dir is already
    # present, so the tree is repacked as-is).
    source_is_checkout: bool = False
    # Set by a transform step that edits the shared source tree in place, to
    # request the end-of-stage repack above.
    source_dirty: bool = False

    def __post_init__(self) -> None:
        # Same list object, not a copy: as FetchStage extends `artifacts`,
        # `report.artifacts` (and report.to_dict()) reflect it automatically --
        # no separate "collect artifacts into the report" step needed anywhere.
        self.report.artifacts = self.artifacts

    def find_artifact(self, output_name: str) -> FetchedArtifact:
        for artifact in self.artifacts:
            if artifact.output_name == output_name:
                return artifact
        raise GorgetConfigError(f"No fetched artifact named {output_name!r}")
