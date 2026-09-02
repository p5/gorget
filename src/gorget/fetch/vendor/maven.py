"""Vendor Maven dependencies into a project-local repository."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class MavenVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        if not (module_dir / "pom.xml").is_file():
            raise GorgetConfigError(f"maven vendor: no pom.xml found in {module_dir}")

        vendor_dir = module_dir / "vendor"
        cmd = [
            "mvn",
            "dependency:go-offline",
            f"-Dmaven.repo.local={vendor_dir}",
            "-DskipTests",
        ]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"mvn dependency:go-offline failed in {module_dir}: {result.stderr.strip()}"
            )
        return vendor_dir

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []
