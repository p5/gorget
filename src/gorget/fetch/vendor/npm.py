from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform, _DEFAULT_NPM_PLATFORMS
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class NpmVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        resolved = platforms or _DEFAULT_NPM_PLATFORMS
        cache_dir = module_dir / ".npm-cache"
        cache_dir.mkdir(exist_ok=True)
        for platform in resolved:
            cmd = [
                "npm", "install",
                "--ignore-scripts", "--no-audit", "--no-fund",
                "--cache", str(cache_dir),
                "--cpu", platform.cpu,
                "--os", platform.os,
                "--libc", platform.libc,
            ]
            result = run(wrap_command(cmd, toolchain), cwd=module_dir)
            if result.returncode != 0:
                raise GorgetTransientError(
                    f"npm install failed for {platform.cpu}/{platform.os}/{platform.libc} "
                    f"in {module_dir}: {result.stderr.strip()}"
                )
            # Clean node_modules between platform iterations
            node_modules = module_dir / "node_modules"
            if node_modules.exists():
                shutil.rmtree(node_modules)
        return cache_dir
