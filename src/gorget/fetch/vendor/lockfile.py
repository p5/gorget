"""Parse npm/pnpm/yarn lockfiles for bundled dependency provides.

These are pure parsers over a lockfile on disk -- no vendoring, no network.
The `bundled-provides` post step reads them straight from the fetched source
tree (each module's `package-lock.json`/`pnpm-lock.yaml`/`yarn.lock`) to
generate the RPM `Provides: bundled(npm(...))` block, so the provides reflect
whatever the tree actually locks (including any `vendor-bump` edits made
earlier in the pipeline).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from pathlib import Path
from typing import Any

PACKAGE_NAME_RE = re.compile(r"^(?:@[^/@]+/)?[^/@]+$")


def npm_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Returns (production, all) sets of (name, version) tuples."""
    text = lockfile.read_text()
    data = json.loads(text) if text.strip() else {}
    production: set[tuple[str, str]] = set()
    all_deps: set[tuple[str, str]] = set()

    packages = data.get("packages")
    if packages:
        # lockfileVersion 2/3: flat `packages` map keyed by install path.
        for path, pkg in packages.items():
            version = pkg.get("version")
            if not path or not version or "node_modules/" not in path:
                continue
            name = pkg.get("name") or path.rsplit("node_modules/", 1)[1]
            if not PACKAGE_NAME_RE.fullmatch(name):
                continue
            all_deps.add((name, version))
            if not pkg.get("dev"):
                production.add((name, version))
    else:
        # lockfileVersion 1 (npm <7): nested `dependencies` tree, no `packages`.
        _npm_v1_walk(data.get("dependencies", {}), production, all_deps)
    return production, all_deps


def _npm_v1_walk(
    deps: dict, production: set[tuple[str, str]], all_deps: set[tuple[str, str]]
) -> None:
    for name, info in deps.items():
        if not isinstance(info, dict):
            continue
        version = info.get("version")
        if version and PACKAGE_NAME_RE.fullmatch(name):
            all_deps.add((name, version))
            if not info.get("dev"):
                production.add((name, version))
        _npm_v1_walk(info.get("dependencies", {}), production, all_deps)


def pnpm_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Returns (production, all) sets from pnpm-lock.yaml."""
    import yaml

    data = yaml.safe_load(lockfile.read_text())
    if not data:  # empty or whitespace-only lockfile -> nothing bundled
        return set(), set()
    snapshots = data.get("snapshots", {})

    # BFS from importers' non-dev dependencies for production
    prod_queue: list[str] = []
    all_queue: list[str] = []
    for importer in data.get("importers", {}).values():
        for section in ("dependencies", "optionalDependencies"):
            for name, dep in importer.get(section, {}).items():
                ref = _pnpm_reference(name, dep)
                if ref:
                    prod_queue.append(ref)
                    all_queue.append(ref)
        for name, dep in importer.get("devDependencies", {}).items():
            ref = _pnpm_reference(name, dep)
            if ref:
                all_queue.append(ref)

    production = _pnpm_walk(prod_queue, snapshots)
    all_deps = _pnpm_walk(all_queue, snapshots)
    return production, all_deps


def _pnpm_walk(queue: list[str], snapshots: dict) -> set[tuple[str, str]]:
    visited: set[str] = set()
    provides: set[tuple[str, str]] = set()
    while queue:
        key = queue.pop()
        if key in visited:
            continue
        visited.add(key)
        package_key = key.split("(", 1)[0]
        name, _, version = package_key.rpartition("@")
        if name and PACKAGE_NAME_RE.fullmatch(name) and version:
            provides.add((name, version))
        snapshot = snapshots.get(key)
        if snapshot:
            for section in ("dependencies", "optionalDependencies"):
                for dep_name, dep in snapshot.get(section, {}).items():
                    ref = _pnpm_reference(dep_name, dep)
                    if ref:
                        queue.append(ref)
    return provides


def _pnpm_reference(name: str, dependency: object) -> str | None:
    reference = dependency.get("version") if isinstance(dependency, dict) else dependency
    if not isinstance(reference, str) or reference.startswith(("link:", "workspace:", "file:")):
        return None
    if reference.startswith("npm:"):
        alias, _, version = reference[4:].rpartition("@")
        return f"{alias}@{version}" if _ else None
    return f"{name}@{reference}"


def yarn_provides(lockfile: Path) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Returns (production, all) from yarn.lock.

    yarn.lock doesn't distinguish dev/prod -- return same set for both.
    """
    text = lockfile.read_text()
    provides: set[tuple[str, str]] = set()
    current_name: str | None = None
    for line in text.splitlines():
        # Entry headers look like: "lodash@^4.17.0":
        # or: "@babel/core@^7.0.0":
        header_match = re.match(r'^"?(@?[^@\s"]+)@', line)
        if header_match and not line.startswith(" "):
            current_name = header_match.group(1)
        elif line.strip().startswith("version ") and current_name:
            version = line.strip().split('"')[1] if '"' in line else line.strip().split()[-1]
            if version and PACKAGE_NAME_RE.fullmatch(current_name):
                provides.add((current_name, version))
            current_name = None
    return provides, provides


def parse_bundled_provides(
    ecosystem: str, source_dir: Path, modules: Sequence[Any]
) -> dict[str, list[tuple[str, str]]]:
    """Parse lockfiles from vendored modules, return production and all provides."""
    _LOCKFILE_PARSERS: dict[str, tuple[str, Any]] = {
        "npm": ("package-lock.json", npm_provides),
        "pnpm": ("pnpm-lock.yaml", pnpm_provides),
        "yarn": ("yarn.lock", yarn_provides),
    }

    lockfile_name, parser = _LOCKFILE_PARSERS[ecosystem]
    production: set[tuple[str, str]] = set()
    all_deps: set[tuple[str, str]] = set()

    for module in modules:
        lockfile = source_dir / module.path / lockfile_name
        if lockfile.is_file():
            prod, all_d = parser(lockfile)
            production.update(prod)
            all_deps.update(all_d)

    return {
        "production": sorted(production),
        "all": sorted(all_deps),
    }
