"""Tests for lockfile parsers (npm, pnpm, yarn)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from gorget.config.schema import VendorModule
from gorget.fetch.vendor.lockfile import (
    npm_provides,
    parse_bundled_provides,
    pnpm_provides,
    yarn_provides,
)


# -- npm --

def _write_npm_lockfile(tmp_path: Path, packages: dict) -> Path:
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(json.dumps({"packages": packages}))
    return lockfile


def test_npm_provides_filters_dev(tmp_path):
    lockfile = _write_npm_lockfile(tmp_path, {
        "": {"version": "1.0.0"},  # root -- skipped (empty path)
        "node_modules/lodash": {"version": "4.17.21"},
        "node_modules/jest": {"version": "29.0.0", "dev": True},
    })
    production, all_deps = npm_provides(lockfile)
    assert ("lodash", "4.17.21") in production
    assert ("jest", "29.0.0") not in production
    assert ("jest", "29.0.0") in all_deps
    assert ("lodash", "4.17.21") in all_deps


def test_npm_provides_skips_root(tmp_path):
    lockfile = _write_npm_lockfile(tmp_path, {
        "": {"version": "1.0.0"},
    })
    production, all_deps = npm_provides(lockfile)
    assert production == set()
    assert all_deps == set()


def test_npm_provides_uses_name_field(tmp_path):
    lockfile = _write_npm_lockfile(tmp_path, {
        "node_modules/@scope/pkg": {"name": "@scope/pkg", "version": "2.0.0"},
    })
    production, all_deps = npm_provides(lockfile)
    assert ("@scope/pkg", "2.0.0") in production


def test_npm_provides_extracts_name_from_path(tmp_path):
    lockfile = _write_npm_lockfile(tmp_path, {
        "node_modules/simple": {"version": "1.0.0"},
    })
    production, _ = npm_provides(lockfile)
    assert ("simple", "1.0.0") in production


# -- pnpm --

def test_pnpm_provides_basic(tmp_path):
    """pnpm lockfile with importers and snapshots."""
    import yaml
    lockfile = tmp_path / "pnpm-lock.yaml"
    data = {
        "importers": {
            ".": {
                "dependencies": {
                    "lodash": {"version": "4.17.21"},
                },
                "devDependencies": {
                    "jest": {"version": "29.0.0"},
                },
            }
        },
        "snapshots": {
            "lodash@4.17.21": {},
            "jest@29.0.0": {
                "dependencies": {
                    "chalk": "5.0.0",
                },
            },
            "chalk@5.0.0": {},
        },
    }
    lockfile.write_text(yaml.dump(data))
    production, all_deps = pnpm_provides(lockfile)
    assert ("lodash", "4.17.21") in production
    assert ("jest", "29.0.0") not in production
    assert ("jest", "29.0.0") in all_deps
    # chalk is a transitive dep of jest (dev), so only in all
    assert ("chalk", "5.0.0") in all_deps
    assert ("chalk", "5.0.0") not in production


def test_pnpm_provides_transitive_prod(tmp_path):
    """Transitive production deps are included in production set."""
    import yaml
    lockfile = tmp_path / "pnpm-lock.yaml"
    data = {
        "importers": {
            ".": {
                "dependencies": {
                    "express": {"version": "4.18.0"},
                },
            }
        },
        "snapshots": {
            "express@4.18.0": {
                "dependencies": {
                    "body-parser": "1.20.0",
                },
            },
            "body-parser@1.20.0": {},
        },
    }
    lockfile.write_text(yaml.dump(data))
    production, all_deps = pnpm_provides(lockfile)
    assert ("express", "4.18.0") in production
    assert ("body-parser", "1.20.0") in production


# -- yarn --

def test_yarn_provides_basic(tmp_path):
    lockfile = tmp_path / "yarn.lock"
    lockfile.write_text("""\
# yarn lockfile v1

"lodash@^4.17.0":
  version "4.17.21"
  resolved "https://registry.yarnpkg.com/lodash/-/lodash-4.17.21.tgz"

"@babel/core@^7.0.0":
  version "7.23.0"
  resolved "https://registry.yarnpkg.com/@babel/core/-/core-7.23.0.tgz"
""")
    production, all_deps = yarn_provides(lockfile)
    assert ("lodash", "4.17.21") in production
    assert ("@babel/core", "7.23.0") in production
    # yarn doesn't distinguish dev/prod
    assert production == all_deps


# -- parse_bundled_provides --

def test_parse_bundled_provides_npm(tmp_path):
    module_dir = tmp_path / "web"
    module_dir.mkdir()
    lockfile = module_dir / "package-lock.json"
    lockfile.write_text(json.dumps({
        "packages": {
            "node_modules/react": {"version": "18.2.0"},
            "node_modules/jest": {"version": "29.0.0", "dev": True},
        }
    }))
    modules = [VendorModule(path="web")]
    result = parse_bundled_provides("npm", tmp_path, modules)
    assert ("jest", "29.0.0") not in result["production"]
    assert ("react", "18.2.0") in result["production"]
    assert ("jest", "29.0.0") in result["all"]
    assert ("react", "18.2.0") in result["all"]


def test_parse_bundled_provides_missing_lockfile(tmp_path):
    modules = [VendorModule(path=".")]
    result = parse_bundled_provides("npm", tmp_path, modules)
    assert result["production"] == []
    assert result["all"] == []
