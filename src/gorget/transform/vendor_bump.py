"""`vendor-bump` transform step: bump a vendored dependency to a minimum version by
editing the ecosystem's lockfile/manifest -- before a later `vendor` step (also a
legal step type under `transform:`) re-vendors against the updated constraint.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from gorget.config.schema import ToolchainEntry, VendorBumpEntry, VendorBumpStep
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.state import StageState
from gorget.toolchain import wrap_command
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.util.subprocess_run import run


class _PinStrategy(Protocol):
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None: ...


class _GoPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        require = f"-require={entry.dependency}@{entry.minimum_version}"
        result = run(wrap_command(["go", "mod", "edit", require], toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"go mod edit failed in {module_dir}: {result.stderr.strip()}"
            )

        result = run(wrap_command(["go", "mod", "tidy"], toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"go mod tidy failed in {module_dir}: {result.stderr.strip()}"
            )


class _NpmPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        data = json.loads(package_json.read_text())
        found = False
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = f">={entry.minimum_version}"
                found = True
        if not found:
            raise GorgetConfigError(
                f"vendor-bump: {entry.dependency} not found in package.json "
                f"dependencies/devDependencies in {module_dir}"
            )
        package_json.write_text(json.dumps(data, indent=2) + "\n")

        cmd = ["npm", "install", "--package-lock-only", "--ignore-scripts"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"npm install --package-lock-only failed in {module_dir}: {result.stderr.strip()}"
            )


class _CargoPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        cargo_toml = module_dir / "Cargo.toml"
        if not cargo_toml.is_file():
            raise GorgetConfigError(f"vendor-bump: no Cargo.toml found in {module_dir}")

        text = cargo_toml.read_text()
        pattern = re.compile(
            rf'^(\s*{re.escape(entry.dependency)}\s*=\s*")[^"]*(")', re.MULTILINE
        )
        new_text, count = pattern.subn(rf"\g<1>>={entry.minimum_version}\g<2>", text)
        if count == 0:
            raise GorgetConfigError(
                f"vendor-bump: {entry.dependency} not found as a simple inline dependency in "
                f"{cargo_toml} (table form [dependencies.{entry.dependency}] and "
                f"workspace-inherited deps aren't supported)"
            )
        cargo_toml.write_text(new_text)

        result = run(wrap_command(["cargo", "update"], toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"cargo update failed in {module_dir}: {result.stderr.strip()}"
            )


class _PnpmPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        data = json.loads(package_json.read_text())
        found = False
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = f">={entry.minimum_version}"
                found = True
        if not found:
            raise GorgetConfigError(
                f"vendor-bump: {entry.dependency} not found in package.json "
                f"dependencies/devDependencies in {module_dir}"
            )
        package_json.write_text(json.dumps(data, indent=2) + "\n")

        cmd = ["pnpm", "install", "--lockfile-only", "--ignore-scripts"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"pnpm install --lockfile-only failed in {module_dir}: {result.stderr.strip()}"
            )


class _YarnPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        data = json.loads(package_json.read_text())
        found = False
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = f">={entry.minimum_version}"
                found = True
        if not found:
            raise GorgetConfigError(
                f"vendor-bump: {entry.dependency} not found in package.json "
                f"dependencies/devDependencies in {module_dir}"
            )
        package_json.write_text(json.dumps(data, indent=2) + "\n")

        cmd = ["yarn", "upgrade", f"{entry.dependency}@>={entry.minimum_version}"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"yarn upgrade failed in {module_dir}: {result.stderr.strip()}"
            )


_STRATEGIES: dict[str, _PinStrategy] = {
    "go": _GoPin(),
    "npm": _NpmPin(),
    "pnpm": _PnpmPin(),
    "yarn": _YarnPin(),
    "cargo": _CargoPin(),
}


class VendorBumpHandler:
    def run(self, step: VendorBumpStep, ctx: TransformContext, state: StageState) -> None:
        if ctx.dry_run:
            return
        source_dir = ensure_source_dir(ctx, state)
        strategy = _STRATEGIES[step.ecosystem]
        for module in step.modules:
            module_dir = source_dir / module.path
            for entry in step.pins:
                strategy.apply(module_dir, entry, ctx.toolchain)
