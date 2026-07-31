"""Mutable state threaded through the stage pipeline (fetch's artifacts feed emit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
    step_outputs: dict[str, dict[str, Any]] = field(default_factory=dict)

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

    def set_step_output(self, step_id: str, key: str, value: Any) -> None:
        if step_id not in self.step_outputs:
            self.step_outputs[step_id] = {}
        self.step_outputs[step_id][key] = value

    def get_step_output(self, dotpath: str) -> Any:
        """Resolve 'steps.<id>.<key>.<subkey>' by walking the nested dict."""
        parts = dotpath.split(".")
        if parts[0] != "steps" or len(parts) < 3:
            raise KeyError(f"invalid output reference: {dotpath}")
        step_id = parts[1]
        if step_id not in self.step_outputs:
            raise KeyError(f"no outputs from step '{step_id}'")
        current: Any = self.step_outputs[step_id]
        for part in parts[2:]:
            if isinstance(current, dict):
                current = current[part]
            else:
                raise KeyError(f"cannot resolve '{part}' in {dotpath}")
        return current
