from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
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
        store_dir = module_dir / ".pnpm-store"
        store_dir.mkdir(exist_ok=True)
        cmd = [
            "pnpm", "fetch",
            "--frozen-lockfile",
            "--store-dir", str(store_dir),
        ]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir, env={"CI": "true"})
        if result.returncode != 0:
            raise GorgetTransientError(
                f"pnpm fetch failed in {module_dir}: {result.stderr.strip()}"
            )
        return store_dir
