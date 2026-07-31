"""Dataclass model for the ``*.source-pipeline.yaml`` schema.

The ``fetch``, ``transform``, ``toolchain``, ``verify``, ``policy``, and ``post``
sections have real behavior. ``patches`` still round-trips as an untyped passthrough
structure so the parser doesn't choke on a full pipeline YAML, without guessing at a
shape a future story owns.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class MacroSubstitution:
    """A single regex-based text substitution applied to the raw spec file."""

    pattern: str
    replacement: str


@dataclass(frozen=True, kw_only=True)
class SpecUpdateStep:
    type: Literal["spec-update"] = "spec-update"
    set_version: bool = True
    reset_release: str | None = "1"
    substitutions: list[MacroSubstitution] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class SpecSourceStep:
    type: Literal["spec-source"] = "spec-source"
    index: int | None = None
    rename: str | None = None


@dataclass(frozen=True, kw_only=True)
class UrlStep:
    type: Literal["url"] = "url"
    url: str
    filename: str | None = None


@dataclass(frozen=True, kw_only=True)
class GitStep:
    type: Literal["git"] = "git"
    repo: str
    ref: str
    shallow: bool = True
    # Recursively init submodules after checkout. "none" skips them, "shallow"
    # clones each submodule at --depth 1 (no history), "full" clones full
    # submodule history. Independent of `shallow`, which controls the parent
    # clone.
    submodules: Literal["none", "shallow", "full"] = "none"
    archive_name: str | None = None
    subdir: str | None = None


@dataclass(frozen=True, kw_only=True)
class VendorModule:
    path: str = "."
    name: str | None = None
    # Go-specific: force GOWORK=off for this module even if it has its own
    # go.work (e.g. prometheus deliberately excludes workspace members like
    # compliance/internal/tools from its vendor archive). Ignored for other
    # ecosystems and for modules with no go.work at all.
    use_workspace: bool = True


@dataclass(frozen=True, kw_only=True)
class VendorPlatform:
    cpu: str    # "x64", "arm64"
    os: str     # "linux"
    libc: str   # "glibc"


_DEFAULT_NPM_PLATFORMS: list[VendorPlatform] = [
    VendorPlatform(cpu="x64", os="linux", libc="glibc"),
    VendorPlatform(cpu="arm64", os="linux", libc="glibc"),
]


@dataclass(frozen=True, kw_only=True)
class VendorStep:
    type: Literal["vendor"] = "vendor"
    ecosystem: Literal["go", "npm", "pnpm", "yarn", "cargo", "composer"]
    archive_name: str | None = None
    modules: list[VendorModule] = field(default_factory=lambda: [VendorModule(path=".")])
    platforms: list[VendorPlatform] | None = None


FetchStep = SpecUpdateStep | SpecSourceStep | UrlStep | GitStep | VendorStep

# type-key -> dataclass, used by config/loader.py to dispatch `fetch:` list items.
FETCH_STEP_TYPES: dict[str, type] = {
    "spec-update": SpecUpdateStep,
    "spec-source": SpecSourceStep,
    "url": UrlStep,
    "git": GitStep,
    "vendor": VendorStep,
}


@dataclass(frozen=True, kw_only=True)
class ToolchainEntry:
    name: str
    version: str


@dataclass(frozen=True, kw_only=True)
class StripTarballStep:
    type: Literal["strip-tarball"] = "strip-tarball"
    target: str | None = None
    paths: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PackStep:
    type: Literal["pack"] = "pack"
    # Paths relative to --package-dir, included in the archive verbatim at
    # their own relative path (no injected wrapper directory) -- for
    # packaging a handful of files already checked into the package's own
    # directory (e.g. helper scripts) into a single deterministic archive,
    # without depending on the host's tar/gzip binary version: gzip's
    # compressed output isn't uniquely determined by its input, so two
    # different tar/gzip builds can compress byte-identical content into
    # different bytes.
    files: list[str]
    output: str


@dataclass(frozen=True, kw_only=True)
class VendorBumpEntry:
    dependency: str
    version: str    # "0.39.0" = minimum (>=), "~4.18" = prefix pin


@dataclass(frozen=True, kw_only=True)
class VendorBumpStep:
    type: Literal["vendor-bump"] = "vendor-bump"
    ecosystem: Literal["go", "npm", "pnpm", "yarn", "cargo"]
    pins: list[VendorBumpEntry] = field(default_factory=list)
    modules: list[VendorModule] = field(default_factory=lambda: [VendorModule(path=".")])


@dataclass(frozen=True, kw_only=True)
class BuildUiStep:
    type: Literal["build-ui"] = "build-ui"
    ecosystem: Literal["npm", "yarn"] = "npm"
    script: str = "build"
    path: str = "."
    output_dir: str = "dist"
    archive_name: str | None = None


@dataclass(frozen=True, kw_only=True)
class RunStep:
    type: Literal["run"] = "run"
    command: list[str] = field(default_factory=list)
    path: str = "."
    outputs: list[str] = field(default_factory=list)
    # Explicitly selects which fetched artifact to extract as the source tree,
    # instead of relying on ensure_source_dir()'s "exactly one artifact"
    # guess -- needed as soon as a pipeline fetches more than one artifact
    # (e.g. a tarball plus its detached checksums file).
    target: str | None = None
    # Path (relative to this step's cwd) to a manifest the command writes,
    # one "<output_name>\t<relative-path>" pair per line, for outputs whose
    # name isn't known until the command runs (e.g. a version string
    # discovered from the source tree). Complements the static `outputs:`
    # above, which requires the name to be known upfront.
    discovered_outputs: str | None = None
    # output_names of already-fetched artifacts to materialize into this
    # step's cwd, raw and unextracted -- unlike `target:` (which extracts one
    # artifact to use as the working tree), this is for a script that needs
    # an artifact's actual bytes, e.g. to checksum-verify it itself before a
    # later transform step mutates it (verify: always runs after all of
    # transform:, so it can't check pristine bytes once something upstream
    # of it in transform: has already changed them). Same idiom as
    # `PostRunStep.artifacts`.
    artifacts: list[str] = field(default_factory=list)


# `vendor` is reused verbatim from the fetch schema: a `transform:` list can run
# `vendor-bump` then `vendor` in order (edit lockfiles, then vendor) since Fetch's
# own `vendor` step always runs before Transform and can't do that ordering itself.
TransformStep = StripTarballStep | VendorBumpStep | BuildUiStep | RunStep | VendorStep | PackStep

TRANSFORM_STEP_TYPES: dict[str, type] = {
    "strip-tarball": StripTarballStep,
    "vendor-bump": VendorBumpStep,
    "build-ui": BuildUiStep,
    "run": RunStep,
    "vendor": VendorStep,
    "pack": PackStep,
}


@dataclass(frozen=True, kw_only=True)
class TransformSection:
    steps: list[TransformStep] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class ToolchainSection:
    entries: list[ToolchainEntry] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class GpgSignatureStep:
    type: Literal["gpg-signature"] = "gpg-signature"
    # No auto-select fallback (unlike e.g. strip-tarball's optional `target`) --
    # guessing wrong on a security check is worse than on a convenience transform.
    target: str
    signature: str
    keyring: str


@dataclass(frozen=True, kw_only=True)
class ChecksumFileStep:
    type: Literal["checksum-file"] = "checksum-file"
    target: str
    checksums_file: str
    algorithm: Literal["sha256", "sha512", "sha1", "md5"] = "sha256"


VerifyStep = GpgSignatureStep | ChecksumFileStep

VERIFY_STEP_TYPES: dict[str, type] = {
    "gpg-signature": GpgSignatureStep,
    "checksum-file": ChecksumFileStep,
}


@dataclass(frozen=True, kw_only=True)
class VerifySection:
    steps: list[VerifyStep] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class AcceptedChecksumEntry:
    file: str
    checksum: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class AcceptedChecksumsSection:
    entries: list[AcceptedChecksumEntry] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class VendorConstraintEntry:
    package: str
    ecosystem: Literal["go", "npm", "pnpm", "yarn", "cargo"]
    # Minimum version -- "at least this version," same semantics as vendor-bump.
    version: str
    reason: str


@dataclass(frozen=True, kw_only=True)
class LicenseComplianceSection:
    disallowed: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PolicySection:
    vendor_constraints: list[VendorConstraintEntry] = field(default_factory=list)
    # Runs go mod verify / npm audit / cargo audit against every vendored module found.
    audit: bool = False
    license_compliance: LicenseComplianceSection = field(
        default_factory=LicenseComplianceSection
    )


@dataclass(frozen=True, kw_only=True)
class PatchesSection:
    entries: list[dict] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PostRunStep:
    type: Literal["run"] = "run"
    command: list[str] = field(default_factory=list)
    # output_names of already-fetched/transformed artifacts this step needs to
    # read -- materialized into --package-dir under their output_name before
    # the command runs, since the command's cwd is --package-dir, not the
    # scratch work_dir the artifact actually lives in until Emit.
    artifacts: list[str] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class BundledProvidesStep:
    """Generate an RPM `Provides: bundled(npm(...))` block from lockfiles.

    Self-contained like the `vendor` step: it declares its own `ecosystem` and
    `modules` and parses the lockfiles under `source_dir/<module.path>` itself
    (no cross-step wiring). Writes one sorted `Provides:` line per bundled
    dependency to `output` in `--package-dir`, for the spec to pull in with
    `%include %{S:N}`.
    """

    type: Literal["bundled-provides"] = "bundled-provides"
    ecosystem: Literal["npm", "pnpm", "yarn"]
    modules: list[VendorModule] = field(default_factory=lambda: [VendorModule(path=".")])
    # "production" drops devDependencies (the usual RPM case -- dev tooling
    # isn't shipped); "all" includes them.
    scope: Literal["production", "all"] = "production"
    output: str = "bundled-npm-provides.inc"


PostStep = PostRunStep | BundledProvidesStep

POST_STEP_TYPES: dict[str, type] = {
    "run": PostRunStep,
    "bundled-provides": BundledProvidesStep,
}


@dataclass(frozen=True, kw_only=True)
class PostSection:
    steps: list[PostStep] = field(default_factory=list)


@dataclass(frozen=True, kw_only=True)
class PipelineSpec:
    package: str | None = None
    fetch: list[FetchStep] = field(default_factory=list)
    transform: TransformSection = field(default_factory=TransformSection)
    toolchain: ToolchainSection = field(default_factory=ToolchainSection)
    verify: VerifySection = field(default_factory=VerifySection)
    policy: PolicySection = field(default_factory=PolicySection)
    patches: PatchesSection = field(default_factory=PatchesSection)
    post: PostSection = field(default_factory=PostSection)
    accepted_checksums: AcceptedChecksumsSection = field(
        default_factory=AcceptedChecksumsSection
    )
