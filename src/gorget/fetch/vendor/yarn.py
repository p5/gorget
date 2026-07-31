from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class YarnVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        cache_dir = module_dir / ".yarn-cache"
        cache_dir.mkdir(exist_ok=True)
        cmd = [
            "yarn", "install",
            "--frozen-lockfile",
            "--cache-folder", str(cache_dir),
        ]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"yarn install failed in {module_dir}: {result.stderr.strip()}"
            )
        # Clean node_modules - we only want the cache
        node_modules = module_dir / "node_modules"
        if node_modules.exists():
            shutil.rmtree(node_modules)
        return cache_dir
