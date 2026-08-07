"""`PostStage`: runs after Policy, before Emit. The one place gorget writes
into `--package-dir` rather than the scratch work dir -- for metadata
extracted from validated (fetched/verified/policy-checked) artifacts that
needs to land in the tracked spec file, e.g. refreshing a generated
`Provides:` block from a vendored dependency manifest.

Every other stage treats `--package-dir` as read-only by convention (nothing
in gorget's own code ever writes there, though nothing enforces it at the OS
level either now that native invocation dropped the old podman `:ro` bind
mount). `post:` is the one stage where writing there is the actual point,
made explicit by the pipeline YAML declaring a `post:` section at all -- an
auditor reading the YAML sees exactly which packages mutate their own
package directory and how.

A step's `command` runs with `--package-dir` as its cwd, not the scratch
`work_dir` fetched/vendored artifacts actually live in until Emit (which runs
after Post) copies them out -- so a step that needs to read one declares it
in `artifacts:`, and it's copied into `--package-dir` under its `output_name`
immediately before the command runs.
"""

from __future__ import annotations

import logging
import shutil
from typing import ClassVar

from gorget.config.schema import BundledProvidesStep, PipelineSpec, PostRunStep
from gorget.context import RunContext
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.lockfile import parse_bundled_provides
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run
from gorget.util.version import rpm_version

logger = logging.getLogger("gorget.pipeline")


class PostStage:
    name: ClassVar[str] = "post"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        if not spec.post.steps:
            return StageResult(name=self.name, status="skipped", reason="no post steps declared")
        if ctx.dry_run:
            # This stage exists specifically to write into --package-dir --
            # never do that under --dry-run, which the rest of the pipeline
            # treats as "touch nothing real."
            return StageResult(name=self.name, status="skipped", reason="dry-run")

        for step in spec.post.steps:
            if isinstance(step, BundledProvidesStep):
                self._run_bundled_provides(step, ctx, state)
            else:
                self._run_step(step, ctx, spec, state)

        return StageResult(name=self.name, status="success")

    def _run_bundled_provides(
        self, step: BundledProvidesStep, ctx: RunContext, state: StageState
    ) -> None:
        # Parse straight from the fetched source tree -- the same checkout
        # `vendor`/`vendor-pin` operate on, so provides reflect any bumps.
        if state.source_dir is None:
            raise GorgetTransientError(
                "bundled-provides step requires a source checkout -- add a preceding "
                "'git' fetch step whose lockfiles this step can read"
            )
        provides = parse_bundled_provides(step.ecosystem, state.source_dir, step.modules)
        # Namespace is bundled(npm(...)) for every JS ecosystem: npm/pnpm/yarn
        # all resolve against the npm registry, matching Fedora's convention.
        lines = [
            f"Provides:       bundled(npm({name})) = {rpm_version(version)}"
            for name, version in provides[step.scope]  # already sorted
        ]
        inc_path = ctx.package_dir / step.output
        inc_path.write_text("\n".join(lines) + "\n")
        logger.debug(
            "post step (bundled-provides): wrote %d lines to %s", len(lines), inc_path
        )

    def _run_step(
        self, step: PostRunStep, ctx: RunContext, spec: PipelineSpec, state: StageState
    ) -> None:
        for name in step.artifacts:
            artifact = state.find_artifact(name)
            logger.debug("post step: materializing artifact %s into %s", name, ctx.package_dir)
            shutil.copyfile(artifact.path, ctx.package_dir / name)

        logger.debug("post step: %s", step)
        result = run(wrap_command(step.command, spec.toolchain.entries), cwd=ctx.package_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"post step ({' '.join(step.command)}) failed in {ctx.package_dir}: "
                f"{result.stderr.strip()}"
            )
