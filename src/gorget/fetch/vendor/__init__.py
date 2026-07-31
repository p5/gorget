"""`vendor` step: generate dependency vendor archives for Go, npm, pnpm, yarn,
Cargo, and Composer ecosystems, combining multiple submodules (e.g. etcd) into
one archive.

Reused by both the Fetch stage's `vendor` step and the Transform stage's `vendor`
step (see `fetch/vendor/base.py`'s `VendorRunContext` for why this isn't typed
against the concrete `FetchContext`).
"""

from __future__ import annotations

from gorget.config.schema import VendorStep
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchedArtifact, build_artifact
from gorget.fetch.vendor.base import VendorEcosystem, VendorRunContext
from gorget.fetch.vendor.cargo import CargoVendor
from gorget.fetch.vendor.combine import combine_vendor_archives
from gorget.fetch.vendor.composer import ComposerVendor
from gorget.fetch.vendor.go import GoVendor
from gorget.fetch.vendor.npm import NpmVendor
from gorget.fetch.vendor.pnpm import PnpmVendor
from gorget.fetch.vendor.yarn import YarnVendor
from gorget.util.git import commit_timestamp

_ECOSYSTEMS: dict[str, VendorEcosystem] = {
    "go": GoVendor(),
    "npm": NpmVendor(),
    "pnpm": PnpmVendor(),
    "yarn": YarnVendor(),
    "cargo": CargoVendor(),
    "composer": ComposerVendor(),
}


class VendorHandler:
    def run(self, step: VendorStep, ctx: VendorRunContext) -> list[FetchedArtifact]:
        ecosystem = _ECOSYSTEMS[step.ecosystem]
        archive_name = step.archive_name or f"{ctx.vars.package}-vendor.tar.gz"
        archive_path = ctx.work_dir / archive_name

        if not ctx.dry_run:
            if ctx.source_dir is None:
                raise GorgetConfigError(
                    "A 'vendor' step requires a preceding 'git' step in the same "
                    "pipeline to establish a source checkout to vendor against"
                )
            module_outputs = [
                (
                    module,
                    ecosystem.vendor(
                        ctx.source_dir / module.path,
                        ctx.toolchain,
                        ctx.package_dir,
                        module.use_workspace,
                        step.platforms or (),
                    ),
                )
                for module in step.modules
            ]
            mtime = commit_timestamp(ctx.source_dir)
            combine_vendor_archives(module_outputs, archive_path, mtime=mtime)

        return [build_artifact(archive_path, archive_name, f"vendor:{step.ecosystem}", ctx.dry_run)]
