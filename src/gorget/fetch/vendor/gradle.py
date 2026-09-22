"""Populate a Gradle dependency cache for an offline build."""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from pathlib import Path

from gorget.config.schema import ToolchainEntry
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


class GradleVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        task: str = "build",
    ) -> Path:
        if not _has_gradle_build_file(module_dir):
            raise GorgetConfigError(
                f"gradle vendor: no build.gradle or build.gradle.kts found in {module_dir}"
            )
        task = task.strip()
        if not task:
            raise GorgetConfigError("gradle vendor: task must not be empty")

        vendor_dir = module_dir / "vendor"
        gradle = "./gradlew" if (module_dir / "gradlew").is_file() else "gradle"
        cmd = [gradle, "--no-daemon", task]
        result = run(
            wrap_command(cmd, toolchain),
            cwd=module_dir,
            env={"GRADLE_USER_HOME": str(vendor_dir)},
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise GorgetTransientError(
                f"{shlex.join(cmd)} failed in {module_dir}: {detail}"
            )

        _remove_transient_cache_files(vendor_dir)
        return vendor_dir


def _has_gradle_build_file(module_dir: Path) -> bool:
    return (module_dir / "build.gradle").is_file() or (
        module_dir / "build.gradle.kts"
    ).is_file()


def _remove_transient_cache_files(vendor_dir: Path) -> None:
    """Remove files Gradle uses for cache coordination, not dependency data."""
    if not vendor_dir.is_dir():
        return
    for path in vendor_dir.rglob("*"):
        if path.is_file() and (path.suffix == ".lock" or path.name == "gc.properties"):
            path.unlink()
