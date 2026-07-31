from __future__ import annotations

import json
import re
import shutil
from collections.abc import Sequence
from pathlib import Path

import yaml

from gorget.config.schema import _DEFAULT_NPM_PLATFORMS, ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run

# Berry = yarn v2+. Its CLI, config file (.yarnrc.yml), and cache layout differ
# from classic yarn v1 -- most notably `yarn install` accepts `--immutable`
# instead of v1's `--frozen-lockfile`/`--cache-folder`/`--ignore-scripts`, and
# the cache folder / offline mirror are configured in .yarnrc.yml rather than on
# the command line. Modern projects (grafana, etc.) pin Berry via
# `packageManager` and a `.yarn/releases/*.cjs` binary, and even yarn v1.22 on
# PATH dispatches to that pinned Berry, so the command must match Berry's flags.
_BERRY_CACHE_REL = ".yarn/cache"
_PACKAGE_MANAGER_RE = re.compile(r"^yarn@(\d+)")


class YarnVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        resolved = platforms or _DEFAULT_NPM_PLATFORMS
        berry = self._is_berry(module_dir)
        cache_dir = module_dir / (_BERRY_CACHE_REL if berry else ".yarn-cache")

        self._write_yarnrc(module_dir, resolved, berry=berry)

        if berry:
            # Berry reads cacheFolder/enableScripts from .yarnrc.yml (written
            # above); `--immutable` fails if install would change the lockfile.
            cmd = ["yarn", "install", "--immutable"]
        else:
            cache_dir.mkdir(parents=True, exist_ok=True)
            cmd = [
                "yarn", "install",
                "--frozen-lockfile",
                "--ignore-scripts",
                "--cache-folder", str(cache_dir),
            ]

        result = run(wrap_command(cmd, toolchain), cwd=module_dir)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"yarn install failed in {module_dir}: {result.stderr.strip()}"
            )
        node_modules = module_dir / "node_modules"
        if node_modules.exists():
            shutil.rmtree(node_modules)
        return cache_dir

    def _is_berry(self, module_dir: Path) -> bool:
        """Yarn v2+ (Berry) vs classic v1.

        Prefer package.json's `packageManager` (the authoritative pin), then
        fall back to Berry-only markers: a `.yarnrc.yml` with `yarnPath`, or a
        bundled `.yarn/releases/` binary.
        """
        pkg = module_dir / "package.json"
        if pkg.exists():
            try:
                pm = json.loads(pkg.read_text()).get("packageManager", "")
            except (json.JSONDecodeError, OSError):
                pm = ""
            match = _PACKAGE_MANAGER_RE.match(pm or "")
            if match:
                return int(match.group(1)) >= 2
        yarnrc = module_dir / ".yarnrc.yml"
        if yarnrc.exists():
            cfg = yaml.safe_load(yarnrc.read_text()) or {}
            if "yarnPath" in cfg:
                return True
        return (module_dir / ".yarn" / "releases").is_dir()

    def _write_yarnrc(
        self, module_dir: Path, platforms: Sequence[VendorPlatform], *, berry: bool
    ) -> None:
        """Write the multi-arch (and, for Berry, offline-cache) config.

        `supportedArchitectures` makes Berry fetch every target platform's
        native packages into the cache. Yarn v1 ignores `.yarnrc.yml` entirely
        (it reads `.yarnrc`), so writing it there is harmless for v1 -- the v1
        path drives everything through CLI flags instead.
        """
        config: dict[str, object] = {
            "supportedArchitectures": {
                "os": sorted({p.os for p in platforms}),
                "cpu": sorted({p.cpu for p in platforms}),
                "libc": sorted({p.libc for p in platforms}),
            },
        }
        if berry:
            # Force an in-tree, populated cache instead of the shared global one
            # so the archived cacheFolder actually contains the dependencies.
            config["enableGlobalCache"] = False
            config["cacheFolder"] = _BERRY_CACHE_REL
            config["enableScripts"] = False

        yarnrc = module_dir / ".yarnrc.yml"
        if yarnrc.exists():
            existing = yaml.safe_load(yarnrc.read_text()) or {}
            existing.update(config)
            config = existing
        yarnrc.write_text(yaml.dump(config, default_flow_style=False))
