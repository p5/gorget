"""`vendor-constraints`: confirm every vendored dependency meets its declared
minimum version. Acts as a safety net for `vendor-bump` (confirms the pin took
effect) and catches violations in packages that don't use `vendor-bump` at all --
this check re-runs on every pipeline execution, so a later upstream update
silently reverting a security fix fails closed instead of shipping quietly.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

from gorget.config.schema import VendorConstraintEntry
from gorget.exceptions import GorgetConfigError
from gorget.policy.base import CheckResult, VendoredModule
from gorget.util.subprocess_run import run
from gorget.util.version import meets_minimum


def _resolve_go_version(module_dir: Path, package: str) -> str | None:
    result = run(["go", "list", "-m", package], cwd=module_dir)
    if result.returncode != 0:
        return None
    parts = result.stdout.split()
    return parts[1] if len(parts) >= 2 else None


def _resolve_npm_version(module_dir: Path, package: str) -> str | None:
    lockfile = module_dir / "package-lock.json"
    if lockfile.is_file():
        data = json.loads(lockfile.read_text())
        for path, pkg in data.get("packages", {}).items():
            if not path or "node_modules/" not in path:
                continue
            name = pkg.get("name") or path.rsplit("node_modules/", 1)[1]
            if name == package:
                version = pkg.get("version")
                if isinstance(version, str):
                    return version
    package_json = module_dir / "node_modules" / package / "package.json"
    if package_json.is_file():
        data = json.loads(package_json.read_text())
        version = data.get("version")
        return version if isinstance(version, str) else None
    return None


def _resolve_cargo_version(module_dir: Path, package: str) -> str | None:
    lockfile = module_dir / "Cargo.lock"
    if not lockfile.is_file():
        return None
    data = tomllib.loads(lockfile.read_text())
    versions = [
        entry["version"]
        for entry in data.get("package", [])
        if entry.get("name") == package and "version" in entry
    ]
    if not versions:
        return None
    # Cargo can resolve multiple coexisting versions of the same crate; take the
    # most permissive reading -- at least one resolved instance meets the
    # constraint -- consistent with vendor_constraints' npm resolution, which
    # likewise only checks a single, direct location rather than every nested copy.
    return max(versions, key=lambda v: tuple(int(p) for p in v.split(".") if p.isdigit()))


def _resolve_pnpm_version(module_dir: Path, package: str) -> str | None:
    lockfile = module_dir / "pnpm-lock.yaml"
    if not lockfile.is_file():
        return None
    import yaml
    data = yaml.safe_load(lockfile.read_text())
    for snapshot_key in data.get("snapshots", {}):
        key = snapshot_key.split("(", 1)[0]
        name, _, version = key.rpartition("@")
        if name == package and version:
            return version
    return None


_YARN_VERSION_RE = re.compile(r'^\s+version:?\s+"?([0-9][^"\s]*)"?')


def _resolve_yarn_version(module_dir: Path, package: str) -> str | None:
    """Resolve a package's version from yarn.lock (yarn v1 or Berry v2+).

    Both formats share the shape: an unindented key line lists the requested
    specs (e.g. `nanoid@^3.3.7:` for v1, `"nanoid@npm:^3.3.7":` for Berry),
    followed by an indented `version "x"` (v1) / `version: x` (Berry) line. A
    package can appear in several blocks; return the highest resolved version
    (with overrides/resolutions in play every copy is forced to the same one,
    so any is representative, and max is the safe reading for "satisfies").
    """
    lockfile = module_dir / "yarn.lock"
    if not lockfile.is_file():
        # Some setups keep a package-lock.json alongside yarn; fall back to it.
        if (module_dir / "package-lock.json").is_file():
            return _resolve_npm_version(module_dir, package)
        return None

    versions: list[str] = []
    matching_block = False
    for line in lockfile.read_text().splitlines():
        if line and not line[0].isspace():
            key = line.strip().rstrip(":")
            specs = [spec.strip().strip('"') for spec in key.split(",")]
            matching_block = any(
                spec == package or spec.startswith(package + "@") for spec in specs
            )
        elif matching_block:
            match = _YARN_VERSION_RE.match(line)
            if match:
                versions.append(match.group(1))
                matching_block = False
    if not versions:
        return None
    return max(versions, key=lambda v: tuple(int(p) for p in re.findall(r"\d+", v)[:3]))


def _resolve_maven_version(module_dir: Path, package: str) -> str | None:
    if package.count(":") != 1:
        return None
    cmd = ["mvn"]
    vendor_dir = module_dir / "vendor"
    if vendor_dir.is_dir():
        cmd.extend(["-o", f"-Dmaven.repo.local={vendor_dir}"])
    cmd.extend(["dependency:tree", f"-Dincludes={package}", "-DoutputType=text"])
    result = run(cmd, cwd=module_dir)
    if result.returncode != 0:
        return None
    match = re.search(rf"(?:^|\s){re.escape(package)}:[^:\s]+:([^:\s]+):", result.stdout)
    return match.group(1) if match else None


_RESOLVERS = {
    "go": _resolve_go_version,
    "npm": _resolve_npm_version,
    "pnpm": _resolve_pnpm_version,
    "yarn": _resolve_yarn_version,
    "cargo": _resolve_cargo_version,
    "maven": _resolve_maven_version,
}


def check_vendor_constraints(
    entries: list[VendorConstraintEntry], modules: list[VendoredModule]
) -> list[CheckResult]:
    results = []
    for entry in entries:
        matching = [m for m in modules if m.ecosystem == entry.ecosystem]
        if not matching:
            raise GorgetConfigError(
                f"policy vendor-constraints references ecosystem {entry.ecosystem!r} for "
                f"package {entry.package!r}, but no {entry.ecosystem!r} vendor step was "
                f"found in fetch:/transform:"
            )

        resolve = _RESOLVERS[entry.ecosystem]
        for module in matching:
            actual = resolve(module.path, entry.package)
            if actual is None:
                results.append(
                    CheckResult(
                        type="vendor-constraints",
                        target=entry.package,
                        status="failed",
                        reason=(
                            f"{entry.package} not found in vendored {entry.ecosystem} "
                            f"module at {module.path}"
                        ),
                    )
                )
            elif meets_minimum(actual, entry.version):
                results.append(
                    CheckResult(type="vendor-constraints", target=entry.package, status="passed")
                )
            else:
                results.append(
                    CheckResult(
                        type="vendor-constraints",
                        target=entry.package,
                        status="failed",
                        reason=(
                            f"{entry.package} is {actual}, need >= {entry.version} "
                            f"({entry.reason})"
                        ),
                    )
                )
    return results
