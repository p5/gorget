import tarfile
from unittest.mock import Mock

import pytest

from gorget.config.schema import ToolchainEntry, VendorModule, VendorStep
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError
from gorget.fetch.base import FetchContext
from gorget.fetch.vendor import VendorHandler


def make_ctx(work_dir, source_dir=None, dry_run=False, toolchain=()):
    return FetchContext(
        work_dir=work_dir,
        package_dir=work_dir,
        spec=Mock(),
        vars=SubstitutionVars(
            version="1.2.3", old_version=None, package="foo", spec_file="foo.spec"
        ),
        dry_run=dry_run,
        source_dir=source_dir,
        toolchain=list(toolchain),
    )


def test_vendor_requires_a_preceding_source_dir(tmp_path):
    step = VendorStep(ecosystem="go")
    with pytest.raises(GorgetConfigError, match="preceding 'git' step"):
        VendorHandler().run(step, make_ctx(tmp_path, source_dir=None))


def test_vendor_single_module_produces_archive(tmp_path, mocker):
    """Also a regression test for the single-unnamed-module case wiring
    ecosystem.archive_root_files() through to the archive root: a vendor
    archive containing only "vendor/" gets mis-extracted by
    `go_vendor_license --use-archive` (see GoVendor.archive_root_files), so
    go.sum here must land next to "vendor/", not inside it.
    """
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "go.sum").write_text("checksums")
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "modules.txt").write_text("example.com/x v1.0.0")
        return vendor_dir

    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS",
        {
            "go": Mock(
                vendor=Mock(side_effect=fake_vendor),
                archive_root_files=Mock(side_effect=lambda module_dir: [module_dir / "go.sum"]),
            )
        },
    )
    step = VendorStep(ecosystem="go")
    artifacts = VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir))

    assert artifacts[0].output_name == "foo-vendor.tar.gz"
    with tarfile.open(artifacts[0].path) as tar:
        names = tar.getnames()
    assert any(name.endswith("modules.txt") for name in names)
    assert "go.sum" in names


def test_vendor_multi_submodule_combines_all_modules(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    source_dir = tmp_path / "etcd"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        module_dir.mkdir(parents=True, exist_ok=True)
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / f"{module_dir.name}.txt").write_text("x")
        return vendor_dir

    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS", {"go": Mock(vendor=Mock(side_effect=fake_vendor))}
    )
    step = VendorStep(
        ecosystem="go",
        archive_name="etcd-vendor.tar.gz",
        modules=[
            VendorModule(path="server", name="server"),
            VendorModule(path="etcdctl", name="etcdctl"),
        ],
    )
    artifacts = VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir))

    assert artifacts[0].output_name == "etcd-vendor.tar.gz"
    with tarfile.open(artifacts[0].path) as tar:
        names = set(tar.getnames())
    assert any(n.endswith("server/server.txt") for n in names)
    assert any(n.endswith("etcdctl/etcdctl.txt") for n in names)


def test_vendor_archive_members_use_source_commit_timestamp(tmp_path, mocker):
    """Regression test: vendor archives were stamped with each file's live
    filesystem mtime (module download/install wall-clock time), so re-running
    the same fetch produced a different checksum every time. Members should now
    carry the source checkout's commit timestamp instead.
    """
    mock_commit_timestamp = mocker.patch(
        "gorget.fetch.vendor.commit_timestamp", return_value=1700000000
    )
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        module_dir.mkdir(parents=True, exist_ok=True)
        (module_dir / "go.mod").write_text("module example.com/x")
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir(parents=True, exist_ok=True)
        (vendor_dir / "modules.txt").write_text("example.com/x v1.0.0")
        return vendor_dir

    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS",
        {
            "go": Mock(
                vendor=Mock(side_effect=fake_vendor),
                archive_root_files=Mock(side_effect=lambda module_dir: [module_dir / "go.mod"]),
            )
        },
    )
    step = VendorStep(ecosystem="go")
    artifacts = VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir))

    mock_commit_timestamp.assert_called_once_with(source_dir)
    with tarfile.open(artifacts[0].path) as tar:
        members = tar.getmembers()
        mtimes = {member.mtime for member in members}
    assert mtimes == {1700000000}
    assert any(m.name == "go.mod" for m in members)


def test_vendor_tar_bz2_archive_name_produces_real_bzip2_file(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    source_dir = tmp_path / "etcd"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        module_dir.mkdir(parents=True, exist_ok=True)
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir()
        (vendor_dir / "modules.txt").write_text("example.com/x v1.0.0")
        return vendor_dir

    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS",
        {
            "go": Mock(
                vendor=Mock(side_effect=fake_vendor), archive_root_files=Mock(return_value=[])
            )
        },
    )
    step = VendorStep(ecosystem="go", archive_name="etcd-vendor.tar.bz2")
    artifacts = VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir))

    assert artifacts[0].output_name == "etcd-vendor.tar.bz2"
    assert artifacts[0].path.read_bytes()[:3] == b"BZh"
    with tarfile.open(artifacts[0].path, "r:bz2") as tar:
        names = tar.getnames()
    assert any(name.endswith("modules.txt") for name in names)


def test_vendor_dry_run_skips_ecosystem_and_combine(tmp_path, mocker):
    mock_vendor = Mock()
    mocker.patch("gorget.fetch.vendor._ECOSYSTEMS", {"go": Mock(vendor=mock_vendor)})
    step = VendorStep(ecosystem="go")
    artifacts = VendorHandler().run(step, make_ctx(tmp_path, source_dir=tmp_path, dry_run=True))
    mock_vendor.assert_not_called()
    assert artifacts[0].checksum is None


def test_vendor_threads_toolchain_to_ecosystem(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "x.txt").write_text("x")
        return vendor_dir

    mock_vendor = Mock(side_effect=fake_vendor)
    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS",
        {"go": Mock(vendor=mock_vendor, archive_root_files=Mock(return_value=[]))},
    )
    step = VendorStep(ecosystem="go")
    toolchain = [ToolchainEntry(name="go", version="1.22.0")]
    VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir, toolchain=toolchain))
    mock_vendor.assert_called_once_with(source_dir / ".", toolchain, tmp_path, True, ())


def test_vendor_threads_use_workspace_false_to_ecosystem(tmp_path, mocker):
    """Regression test: a module can have its own go.work but still need
    GOWORK=off forced (e.g. prometheus deliberately excludes workspace
    members like compliance/internal/tools from its vendor archive).
    VendorModule.use_workspace=False must reach the ecosystem's vendor() call.
    """
    mocker.patch("gorget.fetch.vendor.commit_timestamp", return_value=1700000000)
    source_dir = tmp_path / "src"
    source_dir.mkdir()

    def fake_vendor(module_dir, toolchain=(), package_dir=None, use_workspace=True, platforms=()):
        vendor_dir = module_dir / "vendor"
        vendor_dir.mkdir(parents=True)
        (vendor_dir / "x.txt").write_text("x")
        return vendor_dir

    mock_vendor = Mock(side_effect=fake_vendor)
    mocker.patch(
        "gorget.fetch.vendor._ECOSYSTEMS",
        {"go": Mock(vendor=mock_vendor, archive_root_files=Mock(return_value=[]))},
    )
    step = VendorStep(ecosystem="go", modules=[VendorModule(path=".", use_workspace=False)])
    VendorHandler().run(step, make_ctx(tmp_path, source_dir=source_dir))
    mock_vendor.assert_called_once_with(source_dir / ".", [], tmp_path, False, ())
