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

from gorget.config.expression import resolve_expression
from gorget.config.schema import BundledProvidesStep, PipelineSpec, PostRunStep
from gorget.context import RunContext
from gorget.exceptions import GorgetTransientError
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

    def _run_bundled_provides(
        self, step: BundledProvidesStep, ctx: RunContext, state: StageState
    ) -> None:
        logger.debug("post step (bundled-provides): %s", step)
        # Resolve the input expression to get the actual provides list
        input_value = step.input
        if "${{" in input_value:
            input_value = resolve_expression(input_value, state.get_step_output)

        if not isinstance(input_value, list):
            raise GorgetTransientError(
                f"bundled-provides input must resolve to a list, got: {type(input_value).__name__}"
            )

        # Generate Provides lines, sorted by package name
        provides_lines = []
        for name, version in sorted(input_value):
            provides_lines.append(f"Provides:       bundled(npm({name})) = {rpm_version(version)}")

        # Write the .inc file into --package-dir; the spec uses
        # %include %{S:N} to import it -- gorget does not touch the spec.
        inc_path = ctx.package_dir / "bundled-npm-provides.inc"
        inc_path.write_text("\n".join(provides_lines) + "\n")
        logger.debug("post step (bundled-provides): wrote %d lines to %s", len(provides_lines), inc_path)
