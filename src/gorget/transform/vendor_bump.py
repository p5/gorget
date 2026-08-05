"""`vendor-bump` transform step: bump a vendored dependency to a minimum version by
editing the ecosystem's lockfile/manifest -- before a later `vendor` step (also a
legal step type under `transform:`) re-vendors against the updated constraint.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol

import yaml

from gorget.config.schema import ToolchainEntry, VendorBumpEntry, VendorBumpStep
from gorget.exceptions import GorgetConfigError, GorgetTransientError
from gorget.pipeline.state import StageState
from gorget.policy.vendor_constraints import _RESOLVERS
from gorget.toolchain import wrap_command
from gorget.transform.base import TransformContext, ensure_source_dir
from gorget.util.subprocess_run import run
from gorget.util.version import satisfies_constraint

logger = logging.getLogger(__name__)


def _parse_constraint(version: str) -> tuple[str, str]:
    """Parse version into (mode, version).

    Returns ("minimum", "0.39.0") for plain versions,
    or ("prefix", "4.18") for tilde-prefixed versions.
    """
    if version.startswith("~"):
        return ("prefix", version[1:])
    return ("minimum", version)


class _PinStrategy(Protocol):
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None: ...


class _GoPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        mode, ver = _parse_constraint(entry.version)
        # Both modes use the same Go command — Go's MVS naturally picks latest matching.
        require = f"-require={entry.dependency}@{ver}"
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


def _specifier(version: str) -> str:
    mode, ver = _parse_constraint(version)
    return f"~{ver}" if mode == "prefix" else f">={ver}"


def _set_nested(data: dict, path: Sequence[str], key: str, value: str) -> None:
    node = data
    for part in path:
        node = node.setdefault(part, {})
    node[key] = value


def _yarn_is_berry(module_dir: Path) -> bool:
    """Yarn v2+ (Berry) vs classic v1 -- same detection as the yarn vendor."""
    pkg = module_dir / "package.json"
    if pkg.is_file():
        try:
            pm = json.loads(pkg.read_text()).get("packageManager", "")
        except (json.JSONDecodeError, OSError):
            pm = ""
        match = re.match(r"^yarn@(\d+)", pm or "")
        if match:
            return int(match.group(1)) >= 2
    if (module_dir / ".yarnrc.yml").is_file():
        return True
    return (module_dir / ".yarn" / "releases").is_dir()


def _yarn_install_cmd(module_dir: Path) -> list[str]:
    # Berry updates the lockfile from `resolutions` without a full fetch;
    # v1 regenerates yarn.lock honoring `resolutions` on a plain install.
    if _yarn_is_berry(module_dir):
        return ["yarn", "install", "--mode", "update-lockfile"]
    return ["yarn", "install"]


class _JsPin:
    """yarn: force a dependency's version across the whole tree via `resolutions`.

    `resolutions` pins *every* copy of a package -- including nested transitive
    ones, the common CVE-remediation case a plain `dependencies` edit can't
    reach. When the dependency is also declared directly, its declared range is
    reconciled to the same specifier so the manifest doesn't contradict the
    resolution. yarn then regenerates the lockfile (with integrity) from the
    result. (npm and pnpm have their own handlers -- npm because its lockfile
    won't re-apply an override to an already-resolved transitive without a
    targeted re-resolve, pnpm because overrides moved to pnpm-workspace.yaml.)
    """

    def __init__(
        self,
        *,
        overrides_path: tuple[str, ...],
        install_cmd: Callable[[Path], list[str]],
    ) -> None:
        self._overrides_path = overrides_path
        self._install_cmd = install_cmd

    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        specifier = _specifier(entry.version)
        data = json.loads(package_json.read_text())
        # Reconcile the direct declaration if present (keeps the manifest honest).
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = specifier
        # Force every copy (direct + transitive) via the override mechanism.
        _set_nested(data, self._overrides_path, entry.dependency, specifier)
        package_json.write_text(json.dumps(data, indent=2) + "\n")

        cmd = self._install_cmd(module_dir)
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"{cmd[0]} install failed in {module_dir}: {result.stderr.strip()}"
            )


def _npm_basename(lock_key: str) -> str:
    return lock_key.rsplit("node_modules/", 1)[-1] if "node_modules/" in lock_key else lock_key


def _npm_prune_dependents(lock: dict, dependency: str) -> int:
    """Remove the target package and its direct dependents from a package-lock.

    npm treats an existing lock as authoritative: it won't re-apply a new
    `overrides` entry to a transitive dependency that's already resolved. Pruning
    the target -- and every installed package that directly depends on it, so no
    stale pin to the old version survives -- forces npm to re-resolve exactly
    that gap on the next install (honoring the override), while leaving every
    unrelated pin untouched. Only `node_modules/` entries are pruned; project and
    workspace-member roots (no `node_modules/` in the key) are never removed.
    """
    packages = lock.get("packages", {})
    _DEP_FIELDS = (
        "dependencies", "devDependencies", "optionalDependencies", "peerDependencies"
    )
    to_remove = []
    for key, meta in packages.items():
        if "node_modules/" not in key:
            continue  # never prune the root or a workspace member
        if _npm_basename(key) == dependency:
            to_remove.append(key)
            continue
        deps: dict = {}
        for field in _DEP_FIELDS:
            deps.update(meta.get(field, {}))
        if dependency in deps:
            to_remove.append(key)  # a direct dependent -> re-resolve it too
    for key in to_remove:
        del packages[key]
    return len(to_remove)


class _NpmPin:
    """npm: force a dependency (direct or nested transitive) across the tree.

    Writes an `overrides` entry (and reconciles a direct declaration when
    present), then prunes the target + its direct dependents from
    package-lock.json and runs a full `npm install` so npm re-resolves just that
    gap under the override. A plain `npm install --package-lock-only` (or a full
    install without pruning) leaves an already-locked transitive untouched, and
    deleting the whole lock re-resolves *everything*; this keeps the change
    surgical. node_modules is removed afterward -- the later `vendor` step
    rebuilds the offline cache.
    """

    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        specifier = _specifier(entry.version)
        data = json.loads(package_json.read_text())
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = specifier
        _set_nested(data, ("overrides",), entry.dependency, specifier)
        package_json.write_text(json.dumps(data, indent=2) + "\n")

        lockfile = module_dir / "package-lock.json"
        if lockfile.is_file():
            lock = json.loads(lockfile.read_text())
            _npm_prune_dependents(lock, entry.dependency)
            lockfile.write_text(json.dumps(lock, indent=2) + "\n")

        # A full install (not --package-lock-only) is required: only a real
        # resolve re-adds the pruned entries and applies the override.
        cmd = ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"npm install failed in {module_dir}: {result.stderr.strip()}"
            )
        node_modules = module_dir / "node_modules"
        if node_modules.exists():
            shutil.rmtree(node_modules)


class _PnpmPin:
    """pnpm: force a dependency across the tree.

    Unlike npm/yarn, pnpm v10+ no longer reads settings from package.json's
    `pnpm` field -- `overrides` now live in `pnpm-workspace.yaml`. Write them
    there (creating the file if needed), and still reconcile a direct
    declaration in package.json when present. pnpm then regenerates the lockfile.
    """

    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        package_json = module_dir / "package.json"
        if not package_json.is_file():
            raise GorgetConfigError(f"vendor-bump: no package.json found in {module_dir}")

        specifier = _specifier(entry.version)
        data = json.loads(package_json.read_text())
        reconciled = False
        for key in ("dependencies", "devDependencies"):
            if key in data and entry.dependency in data[key]:
                data[key][entry.dependency] = specifier
                reconciled = True
        if reconciled:
            package_json.write_text(json.dumps(data, indent=2) + "\n")

        # Overrides go in pnpm-workspace.yaml (pnpm v10+); package.json's `pnpm`
        # field is ignored by modern pnpm.
        workspace = module_dir / "pnpm-workspace.yaml"
        ws_data = yaml.safe_load(workspace.read_text()) if workspace.is_file() else None
        ws_data = ws_data or {}
        ws_data.setdefault("overrides", {})[entry.dependency] = specifier
        workspace.write_text(yaml.dump(ws_data, default_flow_style=False, sort_keys=False))

        cmd = ["pnpm", "install", "--lockfile-only", "--ignore-scripts"]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"pnpm install --lockfile-only failed in {module_dir}: {result.stderr.strip()}"
            )


class _CargoPin:
    def apply(
        self, module_dir: Path, entry: VendorBumpEntry, toolchain: Sequence[ToolchainEntry]
    ) -> None:
        cargo_toml = module_dir / "Cargo.toml"
        if not cargo_toml.is_file():
            raise GorgetConfigError(f"vendor-bump: no Cargo.toml found in {module_dir}")

        specifier = _specifier(entry.version)
        text = cargo_toml.read_text()
        pattern = re.compile(
            rf'^(\s*{re.escape(entry.dependency)}\s*=\s*")[^"]*(")', re.MULTILINE
        )
        new_text, count = pattern.subn(rf"\g<1>{specifier}\g<2>", text)
        if count > 0:
            # Direct dependency: bump its declared requirement, then let Cargo
            # re-resolve it in the lockfile.
            cargo_toml.write_text(new_text)
            cmd = ["cargo", "update", "-p", entry.dependency]
        else:
            # Transitive dependency: Cargo has no override mechanism, so pin the
            # exact version of the offending crate directly in Cargo.lock. The
            # version is treated as exact here (prefix/minimum semantics don't
            # apply to `--precise`).
            _mode, ver = _parse_constraint(entry.version)
            cmd = ["cargo", "update", "-p", entry.dependency, "--precise", ver]
        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"cargo update failed in {module_dir}: {result.stderr.strip()}"
            )


_STRATEGIES: dict[str, _PinStrategy] = {
    "go": _GoPin(),
    "npm": _NpmPin(),
    "pnpm": _PnpmPin(),
    "yarn": _JsPin(overrides_path=("resolutions",), install_cmd=_yarn_install_cmd),
    "cargo": _CargoPin(),
}


class VendorBumpHandler:
    def run(self, step: VendorBumpStep, ctx: TransformContext, state: StageState) -> None:
        if ctx.dry_run:
            return
        source_dir = ensure_source_dir(ctx, state)
        strategy = _STRATEGIES[step.ecosystem]
        resolve = _RESOLVERS.get(step.ecosystem)
        for module in step.modules:
            module_dir = source_dir / module.path
            for entry in step.pins:
                if resolve:
                    current = resolve(module_dir, entry.dependency)
                    if current and satisfies_constraint(current, entry.version):
                        logger.info(
                            "vendor-bump: %s already at %s (satisfies %s), skipping",
                            entry.dependency, current, entry.version,
                        )
                        continue
                strategy.apply(module_dir, entry, ctx.toolchain)
                # The shared source tree changed; TransformStage repacks the
                # source tarball once at the end so it matches what `vendor`
                # later builds against.
                state.source_dirty = True
                # Confirm the bump actually took: catches a dependency that
                # isn't in the tree at all (typo, or nothing to bump) and a
                # package manager too old to honor overrides.
                if resolve is not None:
                    now = resolve(module_dir, entry.dependency)
                    if now is None:
                        raise GorgetConfigError(
                            f"vendor-bump: {entry.dependency} is not present in the "
                            f"dependency tree at {module_dir} after the bump -- nothing "
                            "to pin (check the dependency name)"
                        )
                    if not satisfies_constraint(now, entry.version):
                        raise GorgetTransientError(
                            f"vendor-bump: {entry.dependency} resolved to {now}, which does "
                            f"not satisfy {entry.version} after the bump (the package "
                            "manager may be too old to honor overrides/resolutions)"
                        )
