from gorget.config.schema import (
    AcceptedChecksumEntry,
    BuildUiStep,
    ChecksumFileStep,
    GitStep,
    GpgSignatureStep,
    PipelineSpec,
    RunStep,
    SpecSourceStep,
    SpecUpdateStep,
    StripTarballStep,
    ToolchainEntry,
    UrlStep,
    VendorBumpStep,
    VendorModule,
    VendorStep,
)


def test_pipeline_spec_defaults_are_empty():
    spec = PipelineSpec()
    assert spec.fetch == []
    assert spec.transform.steps == []
    assert spec.toolchain.entries == []
    assert spec.verify.steps == []
    assert spec.policy.vendor_constraints == []
    assert spec.policy.audit is False
    assert spec.policy.license_compliance.disallowed == []
    assert spec.patches.entries == []
    assert spec.post.steps == []
    assert spec.accepted_checksums.entries == []


def test_spec_update_step_defaults():
    step = SpecUpdateStep()
    assert step.set_version is True
    assert step.reset_release == "1"
    assert step.substitutions == []


def test_spec_source_step_defaults_to_all_indices():
    step = SpecSourceStep()
    assert step.index is None
    assert step.rename is None


def test_url_step_requires_url():
    step = UrlStep(url="https://example.com/x.tar.gz")
    assert step.filename is None


def test_git_step_defaults():
    step = GitStep(repo="https://example.com/x.git", ref="v1.0.0")
    assert step.shallow is True
    assert step.subdir is None


def test_vendor_step_default_single_module():
    step = VendorStep(ecosystem="go")
    assert step.modules == [VendorModule(path=".")]


def test_strip_tarball_step_defaults():
    step = StripTarballStep()
    assert step.target is None
    assert step.paths == []


def test_vendor_bump_step_default_single_module():
    step = VendorBumpStep(ecosystem="go")
    assert step.modules == [VendorModule(path=".")]
    assert step.pins == []


def test_build_ui_step_defaults():
    step = BuildUiStep()
    assert step.ecosystem == "npm"
    assert step.script == "build"
    assert step.path == "."
    assert step.output_dir == "dist"


def test_run_step_defaults():
    step = RunStep(command=["make", "generate"])
    assert step.path == "."
    assert step.outputs == []


def test_toolchain_entry_fields():
    entry = ToolchainEntry(name="go", version="1.22.0")
    assert entry.name == "go"
    assert entry.version == "1.22.0"


def test_gpg_signature_step_requires_target_signature_keyring():
    step = GpgSignatureStep(
        target="foo.tar.gz", signature="foo.tar.gz.asc", keyring="example.gpg"
    )
    assert step.target == "foo.tar.gz"
    assert step.signature == "foo.tar.gz.asc"
    assert step.keyring == "example.gpg"


def test_checksum_file_step_defaults():
    step = ChecksumFileStep(target="foo.tar.gz", checksums_file="SHASUMS256.txt")
    assert step.algorithm == "sha256"


def test_accepted_checksum_entry_fields():
    entry = AcceptedChecksumEntry(file="foo.tar.gz", checksum="deadbeef", reason="republished")
    assert entry.file == "foo.tar.gz"
    assert entry.checksum == "deadbeef"
    assert entry.reason == "republished"


def test_vendor_platform_fields():
    from gorget.config.schema import VendorPlatform
    p = VendorPlatform(cpu="x64", os="linux", libc="glibc")
    assert p.cpu == "x64"
    assert p.os == "linux"
    assert p.libc == "glibc"


def test_vendor_step_accepts_pnpm_ecosystem():
    step = VendorStep(ecosystem="pnpm")
    assert step.ecosystem == "pnpm"


def test_vendor_step_accepts_yarn_ecosystem():
    step = VendorStep(ecosystem="yarn")
    assert step.ecosystem == "yarn"


def test_vendor_step_platforms_default_none():
    step = VendorStep(ecosystem="npm")
    assert step.platforms is None


def test_vendor_step_with_platforms():
    from gorget.config.schema import VendorPlatform
    platforms = [VendorPlatform(cpu="x64", os="linux", libc="glibc")]
    step = VendorStep(ecosystem="npm", platforms=platforms)
    assert step.platforms == platforms


def test_default_npm_platforms():
    from gorget.config.schema import _DEFAULT_NPM_PLATFORMS, VendorPlatform
    assert len(_DEFAULT_NPM_PLATFORMS) == 2
    assert _DEFAULT_NPM_PLATFORMS[0] == VendorPlatform(cpu="x64", os="linux", libc="glibc")
    assert _DEFAULT_NPM_PLATFORMS[1] == VendorPlatform(cpu="arm64", os="linux", libc="glibc")
