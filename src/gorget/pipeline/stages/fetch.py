"""`FetchStage`: dispatches each `fetch:` step to its handler in declared order.

Step order is exactly YAML list order -- a `spec-update` step naturally runs before
any later `spec-source` step just because it appears first, and a `vendor` step
picks up `FetchContext.source_dir` set by an earlier `git` step in the same list.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from gorget.config.schema import (
    GitStep,
    PipelineSpec,
    SpecSourceStep,
    SpecUpdateStep,
    UrlStep,
    VendorStep,
)
from gorget.context import RunContext
from gorget.fetch.base import FetchContext
from gorget.fetch.git import GitHandler
from gorget.fetch.spec_source import SpecSourceHandler
from gorget.fetch.spec_update import SpecUpdateHandler
from gorget.fetch.url import UrlHandler
from gorget.fetch.vendor import VendorHandler
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState

# Each concrete handler's `run()` is typed against its own specific step
# dataclass (e.g. `SpecUpdateStep`), which is the precise type for its
# implementation but doesn't structurally satisfy a single shared Protocol
# under contravariance rules. The dispatch below is correct by construction
# (each key's value is always called with an instance of that exact key) and
# is covered by tests per-handler, so the table is typed loosely rather than
# fighting variance for a dynamic dispatch pattern.
_HANDLERS: dict[type, Any] = {
    SpecUpdateStep: SpecUpdateHandler(),
    SpecSourceStep: SpecSourceHandler(),
    UrlStep: UrlHandler(),
    GitStep: GitHandler(),
    VendorStep: VendorHandler(),
}

logger = logging.getLogger("gorget.pipeline")


class FetchStage:
    name: ClassVar[str] = "fetch"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        fetch_ctx = FetchContext(
            work_dir=state.work_dir,
            package_dir=ctx.package_dir,
            spec=state.spec,
            vars=ctx.vars,
            dry_run=ctx.dry_run,
            toolchain=spec.toolchain.entries,
        )
        for step in spec.fetch:
            handler = _HANDLERS[type(step)]
            logger.debug("fetch step: %s", step)
            source_dir_before = fetch_ctx.source_dir
            artifacts = handler.run(step, fetch_ctx)
            logger.debug("fetch step produced: %s", [a.output_name for a in artifacts])
            state.artifacts.extend(artifacts)
            # The step that first sets source_dir is the `git` clone; its sole
            # artifact is the source tarball backing that checkout. Record it so
            # a later transform step editing the checkout can repack it.
            if source_dir_before is None and fetch_ctx.source_dir is not None and artifacts:
                state.source_artifact = artifacts[0]
                state.source_is_checkout = True
        # Survives past this method's return (unlike `fetch_ctx` itself) so a
        # later Transform stage can reuse the same checkout.
        state.source_dir = fetch_ctx.source_dir
        return StageResult(name=self.name, status="success")
