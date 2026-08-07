import subprocess

import pytest
import yaml

from gorget.config.schema import VendorPlatform
from gorget.exceptions import GorgetTransientError
from gorget.fetch.vendor.yarn import YarnVendor


def _ok(args=None):
    return subprocess.CompletedProcess(args=args or [], returncode=0, stdout="", stderr="")


def _fail(stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr=stderr)


def test_yarn_vendor_runs_install_with_cache_folder(tmp_path, mocker):
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    cache_dir = tmp_path / ".yarn-cache"
    result = YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 1
    assert mock_run.call_args_list == [
        mocker.call(
            [
                "yarn", "install",
                "--frozen-lockfile",
                "--ignore-scripts",
                "--cache-folder", str(cache_dir),
            ],
            cwd=tmp_path,
        ),
    ]
    assert result == cache_dir


def test_yarn_vendor_writes_yarnrc_yml_with_supported_architectures(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    yarnrc = tmp_path / ".yarnrc.yml"
    assert yarnrc.exists()
    data = yaml.safe_load(yarnrc.read_text())
    assert data["supportedArchitectures"]["cpu"] == ["arm64", "x64"]
    assert data["supportedArchitectures"]["os"] == ["linux"]
    assert data["supportedArchitectures"]["libc"] == ["glibc"]


def test_yarn_vendor_merges_existing_yarnrc_yml(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    (tmp_path / ".yarnrc.yml").write_text("nodeLinker: node-modules\n")
    YarnVendor().vendor(tmp_path)
    data = yaml.safe_load((tmp_path / ".yarnrc.yml").read_text())
    assert data["nodeLinker"] == "node-modules"
    assert "supportedArchitectures" in data


def test_yarn_vendor_custom_platforms(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    platforms = [VendorPlatform(cpu="s390x", os="linux", libc="glibc")]
    YarnVendor().vendor(tmp_path, platforms=platforms)
    data = yaml.safe_load((tmp_path / ".yarnrc.yml").read_text())
    assert data["supportedArchitectures"]["cpu"] == ["s390x"]


def test_yarn_vendor_cleans_node_modules(tmp_path, mocker):
    node_modules = tmp_path / "node_modules"

    def create_node_modules(*args, **kwargs):
        node_modules.mkdir(exist_ok=True)
        return _ok()

    mocker.patch("gorget.fetch.vendor.yarn.run", side_effect=create_node_modules)
    mock_rmtree = mocker.patch("gorget.fetch.vendor.yarn.shutil.rmtree")
    YarnVendor().vendor(tmp_path)
    assert mock_rmtree.call_count == 1
    mock_rmtree.assert_called_once_with(node_modules)


def test_yarn_vendor_raises_on_failure(tmp_path, mocker):
    mocker.patch(
        "gorget.fetch.vendor.yarn.run",
        return_value=_fail(stderr="error Couldn't find a package.json"),
    )
    with pytest.raises(GorgetTransientError, match="Couldn't find a package.json"):
        YarnVendor().vendor(tmp_path)


def test_yarn_vendor_creates_cache_dir(tmp_path, mocker):
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    assert (tmp_path / ".yarn-cache").is_dir()


# --- yarn Berry (v2+) ---


def _berry_project(tmp_path):
    (tmp_path / "package.json").write_text('{"packageManager": "yarn@4.15.0"}')


def test_yarn_berry_two_step_install(tmp_path, mocker):
    """Berry runs update-lockfile (regen checksums) then --immutable (populate cache)."""
    _berry_project(tmp_path)
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    result = YarnVendor().vendor(tmp_path)

    assert mock_run.call_count == 2
    step1 = mock_run.call_args_list[0].args[0]
    step2 = mock_run.call_args_list[1].args[0]
    assert step1 == ["yarn", "install", "--mode", "update-lockfile"]
    assert step2 == ["yarn", "install", "--immutable"]
    # No v1-only flags in either call.
    for cmd in (step1, step2):
        assert "--frozen-lockfile" not in cmd
        assert "--ignore-scripts" not in cmd
        assert "--cache-folder" not in cmd
    assert result == tmp_path / ".yarn" / "cache"


def test_yarn_berry_writes_offline_cache_config(tmp_path, mocker):
    _berry_project(tmp_path)
    mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)

    data = yaml.safe_load((tmp_path / ".yarnrc.yml").read_text())
    assert data["enableGlobalCache"] is False
    assert data["cacheFolder"] == ".yarn/cache"
    assert data["enableScripts"] is False
    assert data["compressionLevel"] == 0
    assert data["supportedArchitectures"]["cpu"] == ["arm64", "x64"]


def test_yarn_berry_detected_via_yarnrc_yarnpath(tmp_path, mocker):
    (tmp_path / ".yarnrc.yml").write_text("yarnPath: .yarn/releases/yarn-4.15.0.cjs\n")
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0].args[0] == ["yarn", "install", "--mode", "update-lockfile"]
    assert mock_run.call_args_list[1].args[0] == ["yarn", "install", "--immutable"]
    # Existing yarnPath is preserved, offline-cache config merged in.
    data = yaml.safe_load((tmp_path / ".yarnrc.yml").read_text())
    assert data["yarnPath"] == ".yarn/releases/yarn-4.15.0.cjs"
    assert data["cacheFolder"] == ".yarn/cache"


def test_yarn_berry_detected_via_releases_dir(tmp_path, mocker):
    (tmp_path / ".yarn" / "releases").mkdir(parents=True)
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 2
    assert mock_run.call_args_list[0].args[0] == ["yarn", "install", "--mode", "update-lockfile"]
    assert mock_run.call_args_list[1].args[0] == ["yarn", "install", "--immutable"]


def test_yarn_berry_fails_on_update_lockfile_skips_immutable(tmp_path, mocker):
    """If update-lockfile fails, --immutable never runs."""
    _berry_project(tmp_path)
    mock_run = mocker.patch(
        "gorget.fetch.vendor.yarn.run",
        return_value=_fail(stderr="checksum mismatch"),
    )
    with pytest.raises(GorgetTransientError, match="checksum mismatch"):
        YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 1


def test_yarn_berry_fails_on_immutable_step(tmp_path, mocker):
    """If update-lockfile succeeds but --immutable fails, error is raised."""
    _berry_project(tmp_path)
    mock_run = mocker.patch(
        "gorget.fetch.vendor.yarn.run",
        side_effect=[_ok(), _fail(stderr="immutable check failed")],
    )
    with pytest.raises(GorgetTransientError, match="immutable check failed"):
        YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 2


def test_yarn_v1_single_install_call(tmp_path, mocker):
    """v1 still runs a single install, not the two-step Berry flow."""
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    assert mock_run.call_count == 1
    cmd = mock_run.call_args_list[0].args[0]
    assert "--frozen-lockfile" in cmd
    assert "--mode" not in cmd


def test_yarn_v1_when_package_manager_is_v1(tmp_path, mocker):
    (tmp_path / "package.json").write_text('{"packageManager": "yarn@1.22.22"}')
    mock_run = mocker.patch("gorget.fetch.vendor.yarn.run", return_value=_ok())
    YarnVendor().vendor(tmp_path)
    cmd = mock_run.call_args_list[0].args[0]
    assert "--frozen-lockfile" in cmd and "--cache-folder" in cmd
