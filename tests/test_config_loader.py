from pathlib import Path

import pytest

from gorget.config.loader import build_pipeline_spec, load_yaml, parse_pipeline_spec
from gorget.config.schema import (
    ChecksumFileStep,
    GitStep,
    GpgSignatureStep,
    PostRunStep,
    RunStep,
    SpecSourceStep,
    SpecUpdateStep,
    StripTarballStep,
    ToolchainEntry,
    UrlStep,
    VendorBumpStep,
    VendorStep,
)
from gorget.config.substitution import SubstitutionVars
from gorget.exceptions import GorgetConfigError

FIXTURES = Path(__file__).parent / "fixtures" / "pipelines"


def make_vars():
    return SubstitutionVars(
        version="1.2.3", old_version="1.2.2", package="example", spec_file="example.spec"
    )


def test_load_yaml_malformed_raises_config_error():
    with pytest.raises(GorgetConfigError):
        load_yaml(FIXTURES / "malformed.yaml")


def test_build_pipeline_spec_full_schema_round_trips():
    spec = build_pipeline_spec(FIXTURES / "full-schema.yaml", substitution_vars=make_vars())
    assert spec.package == "example"
    assert len(spec.fetch) == 5
    assert isinstance(spec.fetch[0], SpecUpdateStep)
    assert spec.fetch[0].reset_release == "1"
    assert spec.fetch[0].substitutions[0].replacement == "%global forgeurl https://example.com/example"
    assert isinstance(spec.fetch[1], SpecSourceStep)
    assert isinstance(spec.fetch[2], UrlStep)
    assert spec.fetch[2].url == "https://example.com/example-1.2.3-extra.tar.gz"
    assert isinstance(spec.fetch[3], GitStep)
    assert spec.fetch[3].ref == "v1.2.3"
    assert isinstance(spec.fetch[4], VendorStep)
    assert spec.fetch[4].ecosystem == "go"

    assert len(spec.transform.steps) == 1
    assert isinstance(spec.transform.steps[0], StripTarballStep)
    assert spec.transform.steps[0].paths == ["docs/"]
    assert len(spec.toolchain.entries) == 1
    assert spec.toolchain.entries[0].name == "go"
    assert spec.toolchain.entries[0].version == "1.22"

    assert len(spec.verify.steps) == 1
    assert isinstance(spec.verify.steps[0], GpgSignatureStep)
    assert spec.verify.steps[0].target == "example-1.2.3.tar.gz"
    assert spec.verify.steps[0].keyring == "example.gpg"

    assert len(spec.accepted_checksums.entries) == 1
    assert spec.accepted_checksums.entries[0].file == "example-1.2.2.tar.gz"
    assert spec.accepted_checksums.entries[0].checksum == "deadbeef"

    assert len(spec.policy.vendor_constraints) == 1
    assert spec.policy.vendor_constraints[0].package == "golang.org/x/crypto"
    assert spec.policy.vendor_constraints[0].ecosystem == "go"
    assert spec.policy.vendor_constraints[0].version == "0.31.0"
    assert spec.policy.audit is True
    assert spec.policy.license_compliance.disallowed == ["GPL-3.0-only"]

    # patches remains inert raw passthrough this story.
    assert len(spec.patches.entries) == 1

    assert len(spec.post.steps) == 1
    assert isinstance(spec.post.steps[0], PostRunStep)
    assert spec.post.steps[0].command == ["./generate-bundled-provides.py", "1.2.3"]
    assert spec.post.steps[0].artifacts == ["extra.tar.gz"]


def test_build_pipeline_spec_fetch_only():
    spec = build_pipeline_spec(FIXTURES / "fetch-only.yaml", substitution_vars=make_vars())
    assert spec.fetch == [SpecSourceStep(index=0)]


def test_build_pipeline_spec_vendor_multi_submodule():
    spec = build_pipeline_spec(
        FIXTURES / "vendor-multi-submodule.yaml", substitution_vars=make_vars()
    )
    vendor_step = spec.fetch[1]
    assert isinstance(vendor_step, VendorStep)
    assert [m.path for m in vendor_step.modules] == ["server", "etcdctl", "etcdutl"]
    assert vendor_step.archive_name == "example-vendor.tar.gz"


def test_unknown_fetch_type_raises_config_error():
    with pytest.raises(GorgetConfigError, match="Unknown fetch step type"):
        build_pipeline_spec(FIXTURES / "unknown-fetch-type.yaml", substitution_vars=make_vars())


def test_transform_strip_tarball_step_parses():
    spec = build_pipeline_spec(
        FIXTURES / "transform-strip-tarball.yaml", substitution_vars=make_vars()
    )
    step = spec.transform.steps[0]
    assert isinstance(step, StripTarballStep)
    assert step.target == "foo-1.2.3.tar.gz"
    assert step.paths == ["*/deps/bundled-openssl"]


def test_transform_vendor_bump_then_vendor_sequencing():
    spec = build_pipeline_spec(
        FIXTURES / "transform-vendor-bump.yaml", substitution_vars=make_vars()
    )
    assert isinstance(spec.transform.steps[0], VendorBumpStep)
    assert spec.transform.steps[0].pins[0].dependency == "golang.org/x/net"
    assert spec.transform.steps[0].pins[0].version == "0.23.0"
    assert isinstance(spec.transform.steps[1], VendorStep)
    assert spec.toolchain.entries == [ToolchainEntry(name="go", version="1.22.0")]


def test_transform_run_step_parses():
    spec = build_pipeline_spec(FIXTURES / "transform-run.yaml", substitution_vars=make_vars())
    step = spec.transform.steps[0]
    assert isinstance(step, RunStep)
    assert step.command == ["make", "generate"]
    assert step.outputs == ["generated/"]
    assert step.target == "example-1.2.3.tar.gz"
    assert step.discovered_outputs == "gorget-discovered.tsv"
    assert step.artifacts == ["checksums.txt"]


def test_unknown_transform_type_raises_config_error():
    with pytest.raises(GorgetConfigError, match="Unknown transform step type"):
        build_pipeline_spec(
            FIXTURES / "unknown-transform-type.yaml", substitution_vars=make_vars()
        )


def test_unknown_post_type_raises_config_error():
    with pytest.raises(GorgetConfigError, match="Unknown post step type"):
        build_pipeline_spec(FIXTURES / "unknown-post-type.yaml", substitution_vars=make_vars())


def test_post_run_step_parses():
    spec = build_pipeline_spec(FIXTURES / "post-run.yaml", substitution_vars=make_vars())
    step = spec.post.steps[0]
    assert isinstance(step, PostRunStep)
    assert step.command == ["./refresh-provides.py", "1.2.3"]
    assert step.artifacts == ["foo-1.2.3.tar.gz"]


def test_post_run_step_artifacts_defaults_to_empty_list():
    spec = parse_pipeline_spec(
        {"post": [{"type": "run", "command": ["./refresh-provides.py"]}]}
    )
    assert spec.post.steps[0].artifacts == []


def test_verify_gpg_signature_step_parses():
    spec = build_pipeline_spec(
        FIXTURES / "verify-gpg-signature.yaml", substitution_vars=make_vars()
    )
    step = spec.verify.steps[0]
    assert isinstance(step, GpgSignatureStep)
    assert step.target == "foo-1.2.3.tar.gz"
    assert step.signature == "foo-1.2.3.tar.gz.asc"
    assert step.keyring == "example-project.gpg"


def test_verify_checksum_file_step_parses():
    spec = build_pipeline_spec(
        FIXTURES / "verify-checksum-file.yaml", substitution_vars=make_vars()
    )
    step = spec.verify.steps[0]
    assert isinstance(step, ChecksumFileStep)
    assert step.target == "foo-1.2.3.tar.gz"
    assert step.checksums_file == "SHASUMS256.txt"
    assert step.algorithm == "sha256"


def test_unknown_verify_type_raises_config_error():
    with pytest.raises(GorgetConfigError, match="Unknown verify step type"):
        build_pipeline_spec(FIXTURES / "unknown-verify-type.yaml", substitution_vars=make_vars())


def test_verify_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'verify' section must be a list"):
        parse_pipeline_spec({"verify": {"type": "gpg-signature"}})


def test_accepted_checksums_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'accepted-checksums' section must be a list"):
        parse_pipeline_spec({"accepted-checksums": {"file": "x"}})


def test_transform_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'transform' section must be a list"):
        parse_pipeline_spec({"transform": {"type": "run"}})


def test_toolchain_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'toolchain' section must be a list"):
        parse_pipeline_spec({"toolchain": {"name": "go"}})


def test_unknown_top_level_key_is_ignored_not_fatal():
    spec = parse_pipeline_spec({"totally-unknown-section": {"x": 1}})
    assert spec.fetch == []


def test_fetch_section_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'fetch' section must be a list"):
        parse_pipeline_spec({"fetch": {"type": "url"}})


def test_missing_pipeline_file_raises_config_error():
    with pytest.raises(GorgetConfigError):
        load_yaml(FIXTURES / "does-not-exist.yaml")


def test_policy_section_must_be_a_mapping():
    with pytest.raises(GorgetConfigError, match="'policy' section must be a mapping"):
        parse_pipeline_spec({"policy": ["not-a-mapping"]})


def test_policy_vendor_constraints_must_be_a_list():
    with pytest.raises(GorgetConfigError, match="'policy.vendor-constraints' must be a list"):
        parse_pipeline_spec({"policy": {"vendor-constraints": {"package": "x"}}})


def test_policy_license_compliance_must_be_a_mapping():
    with pytest.raises(GorgetConfigError, match="'policy.license-compliance' must be a mapping"):
        parse_pipeline_spec({"policy": {"license-compliance": ["GPL-3.0-only"]}})


def test_policy_defaults_when_section_absent():
    spec = parse_pipeline_spec({})
    assert spec.policy.vendor_constraints == []
    assert spec.policy.audit is False
    assert spec.policy.license_compliance.disallowed == []


def test_step_id_with_dots_rejected():
    with pytest.raises(GorgetConfigError, match="invalid"):
        parse_pipeline_spec({"fetch": [{"type": "vendor", "id": "npm.vendor", "ecosystem": "npm"}]})


def test_duplicate_step_id_rejected():
    with pytest.raises(GorgetConfigError, match="Duplicate"):
        parse_pipeline_spec({
            "fetch": [
                {"type": "vendor", "id": "my-vendor", "ecosystem": "npm"},
                {"type": "vendor", "id": "my-vendor", "ecosystem": "go"},
            ],
        })


def test_step_id_valid_chars_accepted():
    spec = parse_pipeline_spec({
        "fetch": [{"type": "vendor", "id": "npm-vendor_1", "ecosystem": "npm"}],
    })
    assert spec.fetch[0].id == "npm-vendor_1"
