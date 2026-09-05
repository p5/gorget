from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from os import walk
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
        store_dir = Path(tempfile.mkdtemp(prefix="gorget-pnpm-store-"))
        try:
            with _preserve_node_modules(module_dir) as clean_node_modules:
                for platform in resolved:
                    cmd = [
                        "pnpm", "fetch",
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
                            f"pnpm fetch failed for {platform.cpu}/{platform.os} "
                            f"in {module_dir}: {result.stderr.strip()}"
                        )
                    clean_node_modules()
            _normalize_store(store_dir)
            return store_dir
        except BaseException:
            shutil.rmtree(store_dir, ignore_errors=True)
            raise

    def cleanup(self, store_dir: Path) -> None:
        """Remove the temporary store after the common archiver has consumed it."""
        shutil.rmtree(store_dir, ignore_errors=True)

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        return []


def _node_modules_dirs(module_dir: Path) -> list[Path]:
    found: list[Path] = []
    for root, dirs, _files in walk(module_dir):
        if "node_modules" in dirs:
            path = Path(root) / "node_modules"
            found.append(path)
            dirs.remove("node_modules")
    return found


def _normalize_store(store_dir: Path) -> None:
    """Remove checkout-specific metadata and timestamps from pnpm's store."""
    for projects_dir in store_dir.glob("v*/projects"):
        shutil.rmtree(projects_dir, ignore_errors=True)

    for database in store_dir.glob("v*/index.db"):
        with sqlite3.connect(database) as connection:
            rows = connection.execute("SELECT key, data FROM package_index ORDER BY key").fetchall()
            for key, data in rows:
                normalized = bytearray(data)
                start = 0
                # pnpm encodes each file's `checkedAt` value as a MessagePack
                # float64. These are the only float64 values in the package
                # index and contain the fetch wall-clock time.
                while (index := data.find(b"\xcb", start)) >= 0:
                    value_start = index + 1
                    normalized[value_start : value_start + 8] = b"\0" * 8
                    start = value_start + 8
                normalized_data = bytes(normalized)
                if normalized_data != data:
                    connection.execute(
                        "UPDATE package_index SET data = ? WHERE key = ?",
                        (normalized_data, key),
                    )
            connection.commit()
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("PRAGMA journal_mode=DELETE")
            connection.execute("ANALYZE")
            connection.execute("VACUUM")
        database.with_name(f"{database.name}-wal").unlink(missing_ok=True)
        database.with_name(f"{database.name}-shm").unlink(missing_ok=True)


@contextmanager
def _preserve_node_modules(module_dir: Path) -> Iterator[Callable[[], None]]:
    """Remove pnpm installs while restoring any directories supplied upstream."""
    with tempfile.TemporaryDirectory(prefix="gorget-pnpm-modules-") as backup_root_name:
        backup_root = Path(backup_root_name)
        originals = _node_modules_dirs(module_dir)
        for index, original in enumerate(originals):
            shutil.copytree(original, backup_root / str(index), symlinks=True)

        def clean() -> None:
            for path in _node_modules_dirs(module_dir):
                shutil.rmtree(path)
            for index, original in enumerate(originals):
                original.parent.mkdir(parents=True, exist_ok=True)
                shutil.copytree(backup_root / str(index), original, symlinks=True)

        try:
            yield clean
        finally:
            clean()
