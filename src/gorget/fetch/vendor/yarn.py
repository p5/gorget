from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

import yaml

from gorget.config.schema import ToolchainEntry, VendorPlatform, _DEFAULT_NPM_PLATFORMS
from gorget.exceptions import GorgetTransientError
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run


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
        cache_dir = module_dir / ".yarn-cache"
        cache_dir.mkdir(exist_ok=True)

        # Write .yarnrc.yml with supportedArchitectures for yarn v4+.
        # Yarn v1 ignores .yarnrc.yml (it uses .yarnrc), so this is safe
        # for both versions.
        yarnrc = module_dir / ".yarnrc.yml"
        arch_config = {
            "supportedArchitectures": {
                "os": sorted({p.os for p in resolved}),
                "cpu": sorted({p.cpu for p in resolved}),
                "libc": sorted({p.libc for p in resolved}),
            },
        }
        if yarnrc.exists():
            existing = yaml.safe_load(yarnrc.read_text()) or {}
            existing.update(arch_config)
            yarnrc.write_text(yaml.dump(existing, default_flow_style=False))
        else:
            yarnrc.write_text(yaml.dump(arch_config, default_flow_style=False))

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
