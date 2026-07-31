from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import _DEFAULT_NPM_PLATFORMS, ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class PnpmVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        resolved = platforms or _DEFAULT_NPM_PLATFORMS
        store_dir = module_dir / ".pnpm-store"
        store_dir.mkdir(exist_ok=True)
        for platform in resolved:
            cmd = [
                "pnpm", "install",
                "--ignore-scripts", "--frozen-lockfile",
                "--store-dir", str(store_dir),
                "--cpu", platform.cpu,
                "--os", platform.os,
            ]
            result = run(
                wrap_command(cmd, toolchain), cwd=module_dir, env={"CI": "true"}
            )
            if result.returncode != 0:
                raise GorgetTransientError(
                    f"pnpm install failed for {platform.cpu}/{platform.os} "
                    f"in {module_dir}: {result.stderr.strip()}"
                )
            node_modules = module_dir / "node_modules"
            if node_modules.exists():
                shutil.rmtree(node_modules)
        return store_dir
