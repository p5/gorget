"""`TransformStage`: dispatches each `transform:` step to its handler in declared
order. `vendor` is reused from the Fetch stage's step/handler (see
`fetch/vendor/base.py`'s `VendorRunContext`) so a pipeline can run `vendor-bump`
then `vendor` under `transform:` in that order (edit lockfiles, then vendor --
Fetch's own `vendor` step always runs before Transform and can't do that
ordering itself).
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from gorget.config.schema import (
    BuildUiStep,
    PackStep,
    PipelineSpec,
    RunStep,
    StripTarballStep,
    VendorBumpStep,
    VendorStep,
)
from gorget.context import RunContext
from gorget.fetch.base import FetchedArtifact
from gorget.fetch.vendor import VendorHandler
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState
from gorget.transform.base import TransformContext, finalize_source_artifact
from gorget.transform.build_ui import BuildUiHandler
from gorget.transform.pack import PackHandler
from gorget.transform.run_step import RunHandler
from gorget.transform.strip_tarball import StripTarballHandler
from gorget.transform.vendor_bump import VendorBumpHandler

_vendor_handler = VendorHandler()


class _VendorStepAdapter:
    """Adapts the Fetch stage's `VendorHandler` (`run(step, ctx) ->
    list[FetchedArtifact]`) to Transform's `run(step, ctx, state) -> None` shape,
    so `VendorHandler` itself needs no changes to be reused here.
    """

    def run(self, step: VendorStep, ctx: TransformContext, state: StageState) -> None:
        artifacts: list[FetchedArtifact] = _vendor_handler.run(step, ctx)
        state.artifacts.extend(artifacts)


# See `fetch/stages/fetch.py` for why this dict is typed loosely rather than
# fighting Protocol contravariance for a dynamic, type-based dispatch table.
_HANDLERS: dict[type, Any] = {
    StripTarballStep: StripTarballHandler(),
    VendorBumpStep: VendorBumpHandler(),
    BuildUiStep: BuildUiHandler(),
    RunStep: RunHandler(),
    VendorStep: _VendorStepAdapter(),
    PackStep: PackHandler(),
}

logger = logging.getLogger("gorget.pipeline")


class TransformStage:
    name: ClassVar[str] = "transform"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        if not spec.transform.steps:
            return StageResult(
                name=self.name, status="skipped", reason="no transform steps declared"
            )

        transform_ctx = TransformContext(
            work_dir=state.work_dir,
            source_dir=state.source_dir,
            vars=ctx.vars,
            toolchain=spec.toolchain.entries,
            dry_run=ctx.dry_run,
            package_dir=ctx.package_dir,
        )
        for step in spec.transform.steps:
            handler = _HANDLERS[type(step)]
            logger.debug("transform step: %s", step)
            handler.run(step, transform_ctx, state)

        state.source_dir = transform_ctx.source_dir
        # If any step edited the shared source tree in place, repack the source
        # tarball once now (not per-step), so it stays consistent with the tree
        # `vendor` and friends built against.
        finalize_source_artifact(state, dry_run=ctx.dry_run)
        return StageResult(name=self.name, status="success")
