from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from gorget.config.schema import ToolchainEntry, VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.gomod_patch_sync import raise_unless_spec_patches_gomod
from gorget.toolchain import wrap_command
from gorget.util.subprocess_run import run

_CONFIG_FILENAME = "go-vendor-tools.toml"

# Matches a pre_command that directly names go.mod/go.sum (e.g. a sed/rm
# targeting the file), or a go subcommand known to rewrite them (`go get`,
# `go mod tidy`/`edit`). Deliberately doesn't match `go mod vendor`/`go
# build`, which read go.mod but don't rewrite its requirements. Mirrors
# rpms/test/test_govendortools_gomod_patch_sync.py's detection -- duplicated
# here since gorget and that monorepo are separate repos, and this is the
# fail-closed version that runs for every gorget-migrated package instead of
# relying on a downstream pytest check to catch drift after the fact.
_GOMOD_MUTATION_RE = re.compile(r"\bgo\.(?:mod|sum)\b|\bgo\s+get\b|\bgo\s+mod\s+(?:tidy|edit)\b")


@dataclass(frozen=True, kw_only=True)
class _ArchiveConfig:
    """The subset of go-vendor-tools.toml's `[archive]` table that affects
    vendor *content* (as opposed to how go-vendor-tools itself packs/compresses
    an archive, which gorget always does its own way). Mirrors go-vendor-tools'
    own `create_archive` command order -- pre_commands, then
    dependency_overrides (each applied via `go get <path>@<version>`), then
    `go mod tidy` if enabled, then `go mod vendor`, then post_commands -- so a
    package's vendored dependencies don't change just because gorget produced
    the archive instead of go-vendor-tools directly.
    """

    pre_commands: list[list[str]] = field(default_factory=list)
    post_commands: list[list[str]] = field(default_factory=list)
    dependency_overrides: dict[str, str] = field(default_factory=dict)
    tidy: bool = True


def _load_archive_config(package_dir: Path | None) -> _ArchiveConfig:
    if package_dir is None:
        return _ArchiveConfig()
    config_path = package_dir / _CONFIG_FILENAME
    if not config_path.is_file():
        return _ArchiveConfig()
    archive = tomllib.loads(config_path.read_text()).get("archive", {})
    return _ArchiveConfig(
        pre_commands=archive.get("pre_commands", []),
        post_commands=archive.get("post_commands", []),
        dependency_overrides=archive.get("dependency_overrides", {}),
        tidy=archive.get("tidy", True),
    )


def _pre_commands_mutate_gomod(pre_commands: list[list[str]]) -> bool:
    return any(_GOMOD_MUTATION_RE.search(" ".join(command)) for command in pre_commands)


def _validate_gomod_patch_sync(package_dir: Path, config: _ArchiveConfig) -> None:
    """gorget's `fetch: {git}` step archives Source0 from the checkout
    *before* handing that same checkout to `vendor:` -- so pre_commands (and
    dependency_overrides, each applied via `go get <path>@<version>`) mutate
    go.mod/go.sum only in the vendor-archive checkout, never in Source0.
    Failing closed here catches a missing spec patch at vendor-archive
    generation time, for every gorget-migrated Go package, instead of
    relying solely on rpms/test/test_govendortools_gomod_patch_sync.py to
    catch it later (that check still matters for non-gorget packages, which
    never reach this code at all). See gomod_patch_sync.py's module
    docstring for the full mechanism -- the same check also runs from
    transform/vendor_pin.py, since a `vendor-pin` step mutates go.mod the
    same way.
    """
    if not (_pre_commands_mutate_gomod(config.pre_commands) or config.dependency_overrides):
        return

    raise_unless_spec_patches_gomod(
        package_dir,
        reason=(
            f"{package_dir / _CONFIG_FILENAME}'s [archive] pre_commands or "
            f"dependency_overrides mutate go.mod/go.sum (a direct edit, `go get`, "
            f"or `go mod tidy`/`edit`)"
        ),
    )


class GoVendor:
    def vendor(
        self,
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry] = (),
        package_dir: Path | None = None,
        use_workspace: bool = True,
        platforms: Sequence[VendorPlatform] = (),
    ) -> Path:
        config = _load_archive_config(package_dir)
        if package_dir is not None:
            _validate_gomod_patch_sync(package_dir, config)

        commands = [
            *config.pre_commands,
            *(
                ["go", "get", f"{import_path}@{version}"]
                for import_path, version in config.dependency_overrides.items()
            ),
        ]
        # A workspace vendors all its modules together into one vendor/ dir at
        # the workspace root: `go mod tidy`/`go mod vendor` refuse to run at
        # all in workspace mode ("cannot be run in workspace mode. Run 'go
        # work vendor' ... or set 'GOWORK=off'"). Go finds the *nearest*
        # go.work by searching upward from cwd, so a module that's a
        # subdirectory of a larger workspace (e.g. etcd's per-submodule
        # archives, vendored independently even though the repo root has its
        # own go.work) would otherwise be swept into that ancestor's
        # workspace mode too -- force GOWORK=off for every command in that
        # case so vendoring stays scoped to just this module, matching how
        # these packages are actually built (e.g. etcd's spec itself sets
        # GOWORK=off for the equivalent build-time step).
        #
        # `use_workspace=False` forces the same GOWORK=off override even when
        # go.work IS directly in module_dir -- some packages have a workspace
        # but deliberately don't want it applied to their vendor archive
        # (e.g. prometheus explicitly excludes workspace members like
        # compliance/internal/tools; confirmed `go work vendor` pulls them in
        # while `GOWORK=off go mod vendor` doesn't).
        use_go_work = use_workspace and (module_dir / "go.work").is_file()
        env = None if use_go_work else {"GOWORK": "off"}
        if use_go_work:
            commands.append(["go", "work", "vendor"])
        else:
            if config.tidy:
                commands.append(["go", "mod", "tidy"])
            commands.append(["go", "mod", "vendor"])
        commands.extend(config.post_commands)

        for command in commands:
            self._run(command, module_dir, toolchain, env)
        return module_dir / "vendor"

    def archive_root_files(self, module_dir: Path) -> list[Path]:
        """go-vendor-tools' own `go_vendor_archive` always packs go.mod/go.sum
        (or go.work/go.work.sum for a workspace) alongside vendor/ at an
        archive's top level -- not just cosmetic convention.
        `go_vendor_license --use-archive`'s merge logic decides whether to
        nest a second archive inside the first (source) archive or treat it
        as an independently-wrapped sibling, based on whether the second
        archive has a single common top-level directory of its own. A vendor
        archive containing *only* "vendor/" has exactly one, so it gets
        treated as independently wrapped and lands as a sibling of the
        extracted source tree instead of nested inside it -- meaning %check's
        license verification can never find the vendored license files at
        their expected paths, and reports every one of them as unexpectedly
        "changed" even though the vendor content itself is untouched (found
        migrating grafana13.1: go-vendor-tools.toml's pins were byte-for-byte
        correct, but `--use-archive` still failed every one of them).
        Including go.mod/go.sum breaks that single-top-level-directory
        heuristic, forcing the correct nested extraction.
        """
        names = (
            ("go.work", "go.work.sum", "go.mod", "go.sum")
            if (module_dir / "go.work").is_file()
            else ("go.mod", "go.sum")
        )
        return [f for name in names if (f := module_dir / name).is_file()]

    def _run(
        self,
        command: list[str],
        module_dir: Path,
        toolchain: Sequence[ToolchainEntry],
        env: dict[str, str] | None,
    ) -> None:
        result = run(wrap_command(command, toolchain), cwd=module_dir, env=env)
        if result.returncode != 0:
            raise GorgetTransientError(
                f"{shlex.join(command)} failed in {module_dir}: {result.stderr.strip()}"
            )
