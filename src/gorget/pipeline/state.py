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
    # reuse it (e.g. for `vendor-bump`/`vendor`/`run` steps) without
    # re-extracting a tarball.
    source_dir: Path | None = None

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
