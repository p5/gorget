"""Load a `*.source-pipeline.yaml` file into a `PipelineSpec`.

Sequencing: yaml.safe_load -> substitute (raw dict/list/str tree) -> parse into
dataclasses. Substitution happens before parsing so the schema/parsing code never
has to reason about `${...}` tokens.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from gorget.config.schema import (
    FETCH_STEP_TYPES,
    POST_STEP_TYPES,
    TRANSFORM_STEP_TYPES,
    VERIFY_STEP_TYPES,
    AcceptedChecksumEntry,
    AcceptedChecksumsSection,
    FetchStep,
    LicenseComplianceSection,
    MacroSubstitution,
    PatchesSection,
    PipelineSpec,
    PolicySection,
    PostSection,
    PostStep,
    ToolchainEntry,
    ToolchainSection,
    TransformSection,
    TransformStep,
    VendorConstraintEntry,
    VendorModule,
    VendorBumpEntry,
    VendorPlatform,
    VerifySection,
    VerifyStep,
)
from gorget.config.substitution import SubstitutionVars, walk_and_substitute
from gorget.exceptions import GorgetConfigError

logger = logging.getLogger(__name__)

_KNOWN_TOP_LEVEL_KEYS = {
    "package",
    "fetch",
    "transform",
    "toolchain",
    "verify",
    "policy",
    "patches",
    "post",
    "accepted-checksums",
}


def load_yaml(path: Path) -> dict:
    try:
        text = path.read_text()
    except OSError as exc:
        raise GorgetConfigError(f"Could not read pipeline YAML {path}: {exc}") from exc
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GorgetConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise GorgetConfigError(f"Pipeline YAML {path} must be a mapping at the top level")
    return raw


def _snake_case_keys(raw: dict) -> dict:
    """YAML keys are kebab-case (e.g. `reset-release`); dataclass fields are snake_case."""
    return {key.replace("-", "_"): value for key, value in raw.items()}


def _parse_fetch_step(raw_step: object) -> FetchStep:
    if not isinstance(raw_step, dict):
        raise GorgetConfigError(f"Each fetch step must be a mapping, got: {raw_step!r}")
    step = _snake_case_keys(raw_step)
    step_type = step.pop("type", None)
    if step_type not in FETCH_STEP_TYPES:
        raise GorgetConfigError(
            f"Unknown fetch step type: {step_type!r} (expected one of "
            f"{sorted(FETCH_STEP_TYPES)})"
        )
    step_cls = FETCH_STEP_TYPES[step_type]
    if step_type == "spec-update" and "substitutions" in step:
        step["substitutions"] = [
            MacroSubstitution(**_snake_case_keys(sub)) for sub in step["substitutions"]
        ]
    if step_type == "vendor" and "modules" in step:
        step["modules"] = [VendorModule(**_snake_case_keys(mod)) for mod in step["modules"]]
    if step_type == "vendor" and "platforms" in step:
        step["platforms"] = [VendorPlatform(**_snake_case_keys(p)) for p in step["platforms"]]
    try:
        return step_cls(**step)
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid {step_type} fetch step: {exc}") from exc


def _parse_transform_step(raw_step: object) -> TransformStep:
    if not isinstance(raw_step, dict):
        raise GorgetConfigError(f"Each transform step must be a mapping, got: {raw_step!r}")
    step = _snake_case_keys(raw_step)
    step_type = step.pop("type", None)
    if step_type not in TRANSFORM_STEP_TYPES:
        raise GorgetConfigError(
            f"Unknown transform step type: {step_type!r} (expected one of "
            f"{sorted(TRANSFORM_STEP_TYPES)})"
        )
    step_cls = TRANSFORM_STEP_TYPES[step_type]
    if step_type == "vendor-bump" and "pins" in step:
        step["pins"] = [VendorBumpEntry(**_snake_case_keys(pin)) for pin in step["pins"]]
    if "modules" in step:
        step["modules"] = [VendorModule(**_snake_case_keys(mod)) for mod in step["modules"]]
    if step_type == "vendor" and "platforms" in step:
        step["platforms"] = [VendorPlatform(**_snake_case_keys(p)) for p in step["platforms"]]
    try:
        return step_cls(**step)
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid {step_type} transform step: {exc}") from exc


def _parse_post_step(raw_step: object) -> PostStep:
    if not isinstance(raw_step, dict):
        raise GorgetConfigError(f"Each post step must be a mapping, got: {raw_step!r}")
    step = _snake_case_keys(raw_step)
    step_type = step.pop("type", None)
    if step_type not in POST_STEP_TYPES:
        raise GorgetConfigError(
            f"Unknown post step type: {step_type!r} (expected one of {sorted(POST_STEP_TYPES)})"
        )
    step_cls = POST_STEP_TYPES[step_type]
    try:
        return step_cls(**step)
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid {step_type} post step: {exc}") from exc


def _parse_toolchain_entry(raw_entry: object) -> ToolchainEntry:
    if not isinstance(raw_entry, dict):
        raise GorgetConfigError(f"Each toolchain entry must be a mapping, got: {raw_entry!r}")
    try:
        return ToolchainEntry(**_snake_case_keys(raw_entry))
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid toolchain entry: {exc}") from exc


def _parse_verify_step(raw_step: object) -> VerifyStep:
    if not isinstance(raw_step, dict):
        raise GorgetConfigError(f"Each verify step must be a mapping, got: {raw_step!r}")
    step = _snake_case_keys(raw_step)
    step_type = step.pop("type", None)
    if step_type not in VERIFY_STEP_TYPES:
        raise GorgetConfigError(
            f"Unknown verify step type: {step_type!r} (expected one of "
            f"{sorted(VERIFY_STEP_TYPES)})"
        )
    step_cls = VERIFY_STEP_TYPES[step_type]
    try:
        return step_cls(**step)
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid {step_type} verify step: {exc}") from exc


def _parse_vendor_constraint_entry(raw_entry: object) -> VendorConstraintEntry:
    if not isinstance(raw_entry, dict):
        raise GorgetConfigError(
            f"Each vendor-constraints entry must be a mapping, got: {raw_entry!r}"
        )
    try:
        return VendorConstraintEntry(**_snake_case_keys(raw_entry))
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid vendor-constraints entry: {exc}") from exc


def _parse_policy_section(raw: dict) -> PolicySection:
    raw_policy = raw.get("policy", {})
    if not isinstance(raw_policy, dict):
        raise GorgetConfigError("The 'policy' section must be a mapping")

    raw_vendor_constraints = raw_policy.get("vendor-constraints", [])
    if not isinstance(raw_vendor_constraints, list):
        raise GorgetConfigError("'policy.vendor-constraints' must be a list of entries")
    vendor_constraints = [
        _parse_vendor_constraint_entry(entry) for entry in raw_vendor_constraints
    ]

    raw_license_compliance = raw_policy.get("license-compliance", {})
    if not isinstance(raw_license_compliance, dict):
        raise GorgetConfigError("'policy.license-compliance' must be a mapping")
    disallowed = raw_license_compliance.get("disallowed", [])
    if not isinstance(disallowed, list):
        raise GorgetConfigError("'policy.license-compliance.disallowed' must be a list")

    return PolicySection(
        vendor_constraints=vendor_constraints,
        audit=bool(raw_policy.get("audit", False)),
        license_compliance=LicenseComplianceSection(disallowed=disallowed),
    )


def _parse_accepted_checksum_entry(raw_entry: object) -> AcceptedChecksumEntry:
    if not isinstance(raw_entry, dict):
        raise GorgetConfigError(
            f"Each accepted-checksums entry must be a mapping, got: {raw_entry!r}"
        )
    try:
        return AcceptedChecksumEntry(**_snake_case_keys(raw_entry))
    except TypeError as exc:
        raise GorgetConfigError(f"Invalid accepted-checksums entry: {exc}") from exc


def parse_pipeline_spec(raw: dict) -> PipelineSpec:
    unknown_keys = set(raw) - _KNOWN_TOP_LEVEL_KEYS
    for key in sorted(unknown_keys):
        logger.warning("Ignoring unknown top-level pipeline YAML key: %s", key)

    raw_fetch = raw.get("fetch", [])
    if not isinstance(raw_fetch, list):
        raise GorgetConfigError("The 'fetch' section must be a list of steps")
    fetch_steps = [_parse_fetch_step(step) for step in raw_fetch]

    raw_transform = raw.get("transform", [])
    if not isinstance(raw_transform, list):
        raise GorgetConfigError("The 'transform' section must be a list of steps")
    transform_steps = [_parse_transform_step(step) for step in raw_transform]

    raw_toolchain = raw.get("toolchain", [])
    if not isinstance(raw_toolchain, list):
        raise GorgetConfigError("The 'toolchain' section must be a list of entries")
    toolchain_entries = [_parse_toolchain_entry(entry) for entry in raw_toolchain]

    raw_verify = raw.get("verify", [])
    if not isinstance(raw_verify, list):
        raise GorgetConfigError("The 'verify' section must be a list of steps")
    verify_steps = [_parse_verify_step(step) for step in raw_verify]

    raw_post = raw.get("post", [])
    if not isinstance(raw_post, list):
        raise GorgetConfigError("The 'post' section must be a list of steps")
    post_steps = [_parse_post_step(step) for step in raw_post]

    raw_accepted_checksums = raw.get("accepted-checksums", [])
    if not isinstance(raw_accepted_checksums, list):
        raise GorgetConfigError("The 'accepted-checksums' section must be a list of entries")
    accepted_checksum_entries = [
        _parse_accepted_checksum_entry(entry) for entry in raw_accepted_checksums
    ]

    return PipelineSpec(
        package=raw.get("package"),
        fetch=fetch_steps,
        transform=TransformSection(steps=transform_steps),
        toolchain=ToolchainSection(entries=toolchain_entries),
        verify=VerifySection(steps=verify_steps),
        policy=_parse_policy_section(raw),
        patches=_parse_list_section(raw, "patches", PatchesSection, "entries"),
        post=PostSection(steps=post_steps),
        accepted_checksums=AcceptedChecksumsSection(entries=accepted_checksum_entries),
    )


def _parse_list_section(raw: dict, key: str, section_cls: type, field_name: str):
    if key not in raw:
        return section_cls()
    value = raw[key]
    if not isinstance(value, list):
        raise GorgetConfigError(f"The '{key}' section must be a list")
    return section_cls(**{field_name: value})


def build_pipeline_spec(path: Path, *, substitution_vars: SubstitutionVars) -> PipelineSpec:
    raw = load_yaml(path)
    substituted = walk_and_substitute(raw, substitution_vars)
    assert isinstance(substituted, dict)
    return parse_pipeline_spec(substituted)


__all__ = [
    "build_pipeline_spec",
    "load_yaml",
    "parse_pipeline_spec",
]
