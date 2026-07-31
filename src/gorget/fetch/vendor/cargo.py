from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class CargoVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        vendor_dir = module_dir / "vendor"
        cmd = ["cargo", "vendor", str(vendor_dir)]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"cargo vendor failed in {module_dir}: {result.stderr.strip()}"
            )
        return vendor_dir
