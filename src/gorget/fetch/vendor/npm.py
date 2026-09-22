from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry
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
        task: str = "build",
    ) -> Path:
        cmd = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"npm install failed in {module_dir}: {result.stderr.strip()}"
            )
        return module_dir / "node_modules"
