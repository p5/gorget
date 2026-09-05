"""Combine one or more per-module vendor directories into a single archive.

A lone module with no explicit name produces a bare `vendor/` at the archive
root -- e.g. cosign, or each of etcd's three independent per-submodule
archives (separate `vendor:` steps, each with exactly one module, not one
archive combining all three). That bare case can also carry `root_files`
(go.mod/go.sum for the `go` ecosystem -- see `VendorEcosystem.archive_root_files`)
alongside `vendor/`, matching go-vendor-tools' own standalone-archive
convention; a `vendor/`-only archive is NOT actually that convention despite
looking like the obvious minimal case (see `archive_root_files`'s docstring).
Multiple modules combined into *one* archive (or a lone module with an
explicit `name` override) instead get their own top-level directory each,
named after `VendorModule.name` or a sanitized form of `VendorModule.path` --
e.g. a single combined `vendor:` step listing all of etcd's submodules as
modules:

    etcd-vendor/
    |-- server/...
    |-- etcdctl/...
    `-- etcdutl/...

`root_files` isn't placed for this multi-module case: each labeled directory
already stands in for an independent module root elsewhere in the source
tree (go.mod/go.sum live in the *source* archive at e.g. `server/go.mod`),
verified instead via go-vendor-tools.toml's `go_mod_dir`, which sidesteps the
single-top-level-directory extraction issue entirely (see
`archive_root_files`'s docstring) by forcing nested extraction regardless.
"""

from __future__ import annotations

import tarfile
from pathlib import Path
from typing import TYPE_CHECKING

from gorget.util.archive import compression_kind, open_gzip_tar

if TYPE_CHECKING:
    from gorget.config.schema import VendorModule


def _default_label(path: str) -> str:
    return path.strip("./").replace("/", "_") or "vendor"


def combine_vendor_archives(
    module_outputs: list[tuple[VendorModule, Path]],
    archive_path: Path,
    *,
    mtime: int | None = None,
    root_files: list[Path] | None = None,
) -> None:
    """Combine per-module vendor directories into a single archive.

    The archive's compression is derived from `archive_path`'s extension
    (`.tar.gz`/`.tgz` for gzip, `.tar.bz2`/`.tbz2` for bzip2, `.tar.xz`/`.txz`
    for xz) so the bytes on disk always match what the filename claims.

    `mtime`, when given, is stamped onto every archive member -- e.g. the
    source checkout's commit timestamp -- in place of the vendor tool's live
    filesystem mtimes (module downloads/installs happen at fetch wall-clock
    time), so re-running the same fetch produces a byte-identical archive.

    `root_files`, when given, are added at the archive's top level alongside
    a *bare* `vendor/` -- ignored for the multi-module/labeled case (see this
    module's docstring for why). The caller is expected to only pass these
    for the single-unnamed-module case in the first place.
    """
    kind = compression_kind(archive_path)
    archive_path.parent.mkdir(parents=True, exist_ok=True)

    def _filter(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        if mtime is not None:
            tarinfo.mtime = mtime
        tarinfo.uid = 0
        tarinfo.gid = 0
        tarinfo.uname = ""
        tarinfo.gname = ""
        return tarinfo

    def _add_all(tar: tarfile.TarFile) -> None:
        # A lone module with no explicit name has nothing to disambiguate
        # against, so it always gets a bare "vendor" -- regardless of its
        # path. Found via etcd: three independent `vendor:` steps (one per
        # submodule, each with a non-trivial path like "server"), each
        # producing its own archive that %prep extracts with `-C server` --
        # so the archive itself must already be bare "vendor/", not
        # "server/vendor/" (that would double the "server/" nesting).
        # An explicit `name` is a deliberate override and is always honored.
        bare_vendor = len(module_outputs) == 1 and module_outputs[0][0].name is None
        for module, vendor_dir in module_outputs:
            arcname = "vendor" if bare_vendor else (module.name or _default_label(module.path))
            tar.add(vendor_dir, arcname=arcname, filter=_filter)
        if bare_vendor and root_files:
            for root_file in root_files:
                tar.add(root_file, arcname=root_file.name, filter=_filter)

    if kind == "gz":
        with open_gzip_tar(archive_path) as tar:
            _add_all(tar)
    elif kind == "bz2":
        with tarfile.open(archive_path, "w:bz2") as tar:
            _add_all(tar)
    else:
        with tarfile.open(archive_path, "w:xz") as tar:
            _add_all(tar)
