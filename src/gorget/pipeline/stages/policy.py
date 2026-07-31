"""`PolicyStage`: validates the final vendored output against declared
constraints. Acts as a safety net for `vendor-bump` (confirms the pin took
effect) and catches violations in packages that don't use `vendor-bump` at all --
this re-runs on every pipeline execution, so a later upstream update silently
reverting a security fix fails the build instead of shipping quietly. All
deterministic failures (vendor-constraints, `go mod verify`, license-compliance)
are aggregated into a single `GorgetPolicyViolation`. `npm audit`/`cargo audit`
findings are warn-only (network-dependent, non-deterministic) and never raise.
"""

from __future__ import annotations

import logging
from typing import ClassVar

from gorget.config.schema import PipelineSpec
from gorget.context import RunContext
from gorget.exceptions import GorgetPolicyViolation
from gorget.pipeline.result import StageResult
from gorget.pipeline.state import StageState
from gorget.policy.audit import run_audits
from gorget.policy.base import CheckResult, discover_vendored_modules
from gorget.policy.license_compliance import check_license_compliance
from gorget.policy.vendor_constraints import check_vendor_constraints

logger = logging.getLogger("gorget.pipeline")


class PolicyStage:
    name: ClassVar[str] = "policy"

    def run(self, ctx: RunContext, spec: PipelineSpec, state: StageState) -> StageResult:
        if ctx.dry_run:
            # Nothing was actually vendored under dry-run (no real node_modules/
            # vendor/ dirs on disk), so there's nothing real to check.
            return StageResult(name=self.name, status="skipped", reason="dry-run")

        policy = spec.policy
        policy_configured = bool(
            policy.vendor_constraints or policy.audit or policy.license_compliance.disallowed
        )
        if not policy_configured:
            logger.warning("No policy configured for %s", ctx.vars.package)
            return StageResult(name=self.name, status="skipped", reason="no policy configured")

        modules = discover_vendored_modules(spec, state.source_dir) if state.source_dir else []

        results: list[CheckResult] = []
        results += check_vendor_constraints(policy.vendor_constraints, modules)
        if policy.audit:
            results += run_audits(modules)
        if policy.license_compliance.disallowed:
            results += check_license_compliance(policy.license_compliance, modules)

        failures = [result for result in results if result.status == "failed"]
        if failures:
            raise GorgetPolicyViolation(_format_failures(failures))

        return StageResult(
            name=self.name, status="success", details=[result.to_dict() for result in results]
        )


def _format_failures(failures: list[CheckResult]) -> str:
    lines = [f"Policy violation ({len(failures)} check(s)):"]
    for failure in failures:
        lines.append(f"- [{failure.type}] {failure.target}: {failure.reason}")
    return "\n".join(lines)
