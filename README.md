# Gorget

**Gorget** is a source-pipeline tool for RPM package supply-chain trust. It
fetches upstream source tarballs directly from their origin (rather than an
intermediate lookaside cache), applies transforms, verifies integrity,
enforces dependency policy, and emits lookaside-ready artifacts.

It's a plain CLI tool, installed like any other build dependency (e.g. via
RPM) and invoked directly -- its `fetch:`/`vendor:` steps already run
untrusted third-party code the same way `go-vendor-tools`/`npm`/`cargo` do,
so it doesn't need or get container isolation those tools don't have either.

Each package gets a declarative `<package>.source-pipeline.yaml` describing
exactly how its sources are produced. When no pipeline YAML exists, gorget
falls back to fetching every `Source` URL declared in the package's spec file.

This is an early-stage implementation covering the **Fetch**, **Transform**,
**Verify**, **Policy**, and **Post** stages and the core framework (config
parsing, variable substitution, the stage pipeline, and a minimal Emit).

## How-to guides

- [Getting started: write your first source-pipeline.yaml](docs/how-to/getting-started.md)
- [Add source verification for a new upstream](docs/how-to/verify-a-new-upstream.md)
- [Hand-patch a vendored dependency, and stop it from regressing](docs/how-to/hand-patch-and-enforce-a-dependency-version.md)
- [Add a policy check to an existing pipeline](docs/how-to/add-a-policy-check.md)
- [Add a post: step to refresh generated metadata](docs/how-to/add-a-post-step.md)
- [Fetch a source whose URL you don't know until runtime](docs/how-to/discover-additional-sources.md)
- [Fetch from a private git repo](docs/how-to/fetch-from-a-private-repo.md)
- [Debug a failing pipeline locally](docs/how-to/debug-a-failing-pipeline.md)

## CLI interface

```
gorget \
  --package-dir ./<package-dir> \
  --pipeline-file ./pipeline.yaml \
  --gpg-keys-dir ./gpg-keys \
  --output-dir ./output \
  --version <new-version> \
  [--old-version <old-version>] \
  [--dry-run]
```

| Flag | Purpose |
|---|---|
| `--package-dir` | Package directory: spec file, patches, sources manifest |
| `--pipeline-file` | The package's pipeline definition (optional) |
| `--gpg-keys-dir` | Centralized GPG keyrings, one armored/binary key file per trusted upstream, referenced by filename from `verify: gpg-signature` steps |
| `--output-dir` | Fetched tarballs, `sources` manifest, `report.json` |

Each of these has a historical default (`/package`, `/pipeline.yaml`,
`/gpg-keys`, `/output` respectively, see [CLI flags](#cli-flags)) from
gorget's original container-mount design, but every real caller passes all
four explicitly -- there's no container providing them implicitly anymore.

## Pipeline steps

### `fetch:`

| Step | Purpose |
|---|---|
| `spec-update` | Bump `Version:`/reset `Release:`/apply declared substitutions, before Source URLs resolve |
| `spec-source` | Download the spec's `Source0`/`SourceN` URLs (macro-resolved), by index or all |
| `url` | Download an explicit URL not declared in the spec |
| `git` | Clone a repo at a tag/branch/commit (optionally with recursive submodules via `submodules: shallow`/`full`; use `full` if the project pins submodules to non-tip commits), archive the checkout (or a subdir) |
| `vendor` | Generate a Go/npm/pnpm/yarn/Cargo/Composer vendor archive (multi-submodule aware, multi-arch for npm) |

`git` (or another real fetch step) is mandatory for a **native package** (no
Fedora dist-git history, so no `Source0` tarball URL to fall back to) --
there's no bare-`spec-source` fallback the way an already-Fedora-derived
package has. `vendor` is only needed on top of that if the package actually
has dependencies to vendor -- exactly the same condition as for any package,
native or not, nothing about it is native-specific. `transform:`/`verify:`/
`policy:`/`post:` are all still available too, same as any other pipeline --
see [`native-cargo-demo`](examples/native-cargo-demo/) for a native package
that happens to need both `git` and `vendor`.

```yaml
fetch:
  - type: git
    repo: "${UPSTREAM_REPO}"   # or a literal URL/local path
    ref: "v${VERSION}"          # tag, branch, or commit SHA
    shallow: true                # default; a SHA-like ref falls back to a
                                  # partial clone instead of true --depth 1
    subdir: null                  # archive just this subdir of the checkout
    archive_name: "${PACKAGE}-${VERSION}.tar.gz"  # default shown; optional

  - type: vendor
    ecosystem: cargo              # go | npm | cargo | composer
    archive_name: "${PACKAGE}-${VERSION}-vendor.tar.xz"  # see note below
    modules:                       # default: [{path: "."}] -- a single
      - path: "."                  # module rooted at the checkout itself
        name: null                  # explicit label (multi-module archives
                                     # only; see combine.py for etcd's case)
```

`git`'s `archive_name` defaults to `${PACKAGE}-${VERSION}.tar.gz` if
omitted. `vendor`'s default is **not** analogous -- `${PACKAGE}-vendor.tar.gz`,
with no version and always gzip -- so a pipeline that wants a versioned
and/or differently-compressed vendor archive (`.tar.bz2`/`.tar.xz`, both
valid, see `gorget/util/archive.py`) must set `archive_name` explicitly.
Nothing cross-checks either default or override against what the spec
file's `Source0`/`SourceN` actually declare, or against `%prep`'s
`%autosetup -n` (which must match the *archive's* internal top-level
directory -- itself just `archive_name` minus its compression suffix, not
the upstream repo's own directory name) -- a mismatch surfaces as a `%prep`
failure several steps removed from the pipeline YAML that caused it.

`vendor`'s `modules` lets one archive combine several submodules (e.g. an
etcd-style repo with independent `server`/`etcdctl`/`etcdutl` Go modules) --
each gets its own labeled top-level directory in the combined archive unless
there's exactly one module with no explicit `name`, which instead produces a
bare `vendor/` at the archive root.

**`git` doesn't manage credentials.** It shells out to a plain `git
clone`/`git checkout`, inheriting whatever ambient git configuration the
process invoking gorget already has (a credential helper, an SSH agent, a
`url.insteadOf` rewrite, `.netrc`) -- there's no gorget-level flag or config
field for a token or key. A private `repo:` with no such ambient auth fails
closed with git's own `fatal: could not read Username for '...': terminal
prompts disabled`. See
[Fetch from a private git repo](docs/how-to/fetch-from-a-private-repo.md).

### `transform:`

Runs after `fetch:`, in declared order, against what was already fetched.

| Step | Purpose |
|---|---|
| `strip-tarball` | Remove paths (glob patterns) from a fetched tarball and repack it |
| `vendor-bump` | Bump a vendored dependency to a minimum or prefix-pinned version (Go/npm/pnpm/yarn/Cargo) by editing its lockfile/manifest, before a later `vendor` step re-vendors. Plain `version: "0.39.0"` means `>=0.39.0`; tilde `version: "~4.18"` pins to latest `4.18.x` |
| `vendor` | Same step as `fetch:`'s `vendor` (reused) -- lets `vendor-bump` run before vendoring, since `fetch:` always runs before `transform:` |
| `build-ui` | Run `npm`/`yarn run <script>` and archive the build output directory |
| `run` | Escape hatch: an arbitrary command, with declared output paths archived as new artifacts afterward |
| `pack` | Archive an explicit list of files already in `--package-dir` into a single deterministic tarball, each at its own relative path |

`vendor-bump`/`vendor`/`build-ui`/`run` all operate against a shared working
source tree: a `git` fetch step's checkout if one ran, otherwise the sole
fetched artifact gets extracted on first use (an error if there's more than
one and no way to tell which to use) -- unless a `run:` step declares
`target:`, naming exactly which fetched artifact to extract instead (needed
as soon as a pipeline fetches more than one artifact, e.g. a tarball plus its
detached checksums file).

`run:`'s `outputs:` archives files/directories whose name is known upfront.
For a name only known once the command runs (e.g. a version string it
discovered from the source tree), declare `discovered-outputs:` instead: a
manifest file (relative to the step's cwd) the command writes, one
`<output_name>\t<path>` pair per line:

```yaml
transform:
  - type: run
    target: "node-v22.9.0.tar.gz"
    command: ["./discover-icu-version.sh"]
    discovered-outputs: "discovered.tsv"   # each line: "<output_name>\t<path>"
```

`run:`'s `artifacts:` materializes already-fetched artifacts' raw,
unextracted bytes into the step's cwd (the same idiom as `post:`'s
`artifacts:` below) -- for a script that needs to read an artifact directly
rather than through `target:`'s extracted view, e.g. checksum-verifying it
manually before a later step in the same `transform:` list mutates it
(`verify:` always runs after all of `transform:`, so it can't see pristine
bytes once something upstream in `transform:` has already changed them).

### `verify:`

Runs after `transform:`. Validates integrity/authenticity of what was
fetched, before Policy and Emit.

| Step | Purpose |
|---|---|
| `gpg-signature` | Verify a detached GPG signature against a keyring in the GPG keys directory (`--gpg-keys-dir`) |
| `checksum-file` | Verify an artifact's digest against an entry in a fetched checksums-listing file (e.g. `SHASUMS256.txt`) |

```yaml
verify:
  - type: gpg-signature
    target: "foo-1.2.3.tar.gz"        # output_name of an already-fetched artifact
    signature: "foo-1.2.3.tar.gz.asc"  # output_name of the fetched detached signature
    keyring: "example-project.asc"      # filename within --gpg-keys-dir

  - type: checksum-file
    target: "foo-1.2.3.tar.gz"
    checksums-file: "SHASUMS256.txt"    # output_name of the fetched checksums listing
    algorithm: sha256                    # sha256 (default) | sha512 | sha1 | md5
```

Unlike `transform:`'s `strip-tarball`, there is no auto-select fallback when
`target`/`signature`/`checksums-file` are omitted -- guessing wrong on a
security check is worse than on a convenience transform, so all three are
required.

`gpg-signature` imports the keyring into a fresh, throwaway GPG homedir per
check (`gpg --homedir <tmp> --import ... && gpg --homedir <tmp> --verify
...`) rather than using `--keyring` directly, for robustness across keyring
formats and modern GPG's keybox-format quirks.

**Re-publication detection runs automatically whenever a `sources` file
exists in the package directory** -- no `verify:` step needed to opt in, since it's the core
supply-chain safety net: every freshly-fetched artifact whose filename is
already recorded in `sources` has its checksum recomputed (at whichever
digest algorithm the existing entry uses) and compared, failing closed if
upstream silently republished a same-named file with different content. A
package with neither an existing `sources` file nor any declared `verify:`
steps gets a non-blocking "no verification configured" warning instead.

All verification failures across all checks -- re-publication and declared
`verify:` steps alike -- are aggregated into one error rather than stopping
at the first failure, so a single run surfaces everything wrong at once.
`report.json`'s `verify` stage includes a `details` list with the per-check
type/target/status/reason.

### `accepted-checksums:`

A top-level section, sibling to `fetch`/`transform`/`verify`/`toolchain`,
for explicitly accepting a re-publication that re-publication detection
would otherwise fail closed on:

```yaml
accepted-checksums:
  - file: "foo-1.2.3.tar.gz"
    checksum: "f871e5f8...747749e2"   # the artifact's sha512, from the failure message
    reason: "Upstream re-cut the tarball to fix line endings; verified by hand"
```

Matching against `sources` uses whatever digest algorithm that file already
records, but `accepted-checksums:` entries are always matched against the
artifact's own **sha512** checksum (gorget's standard, and what the failure
message itself prints) -- copy it straight from the error, don't recompute
it separately. Each entry requires a human-authored `reason:`, so accepting
a re-publication always leaves an audit trail rather than silently
suppressing the check.

### `policy:`

Runs after `verify:`, before Emit. Validates the *final vendored output* --
acts as a safety net for `vendor-bump` (confirms a pin actually took effect)
and catches violations in packages that don't use `vendor-bump` at all. Unlike
`vendor-bump` (a one-time edit), this re-runs on every pipeline execution, so a
later upstream update silently reverting a security fix fails the build
instead of shipping quietly.

```yaml
policy:
  vendor-constraints:
    - package: sanitize-html
      ecosystem: npm        # go | npm | pnpm | yarn | cargo
      version: "2.17.5"      # minimum version -- "at least this version"
      reason: "CVE-2024-XXXXX"

  audit: true                # run go mod verify / npm audit / cargo audit
                              # against every vendored module found

  license-compliance:
    disallowed:
      - GPL-3.0-only
      - AGPL-3.0-only
```

| Check | Behavior |
|---|---|
| `vendor-constraints` | Resolves the actual vendored version (`go list -m`, `node_modules/<pkg>/package.json`, `Cargo.lock`) and compares against the declared minimum. Checks every vendored module for that ecosystem automatically -- no per-entry module path needed. Fails closed. |
| `audit` | `go mod verify` checks module cache checksums against `go.sum` -- deterministic, no network, **fails closed**. `npm audit`/`cargo audit` query live vulnerability databases over the network -- non-deterministic (results can change with no code change), so findings are recorded in `report.json` but are **warn-only, never fail closed**. `cargo-audit` must be separately installed on `PATH`. |
| `license-compliance` | Flags a vendored dependency whose declared license is in `disallowed`. Supported for npm (`package.json`'s `license` field) and Cargo (`Cargo.toml`'s `license` field) only -- Go has no standard machine-readable per-module license field, so Go modules get a single "unsupported" warning instead of a fabricated check. |

A package with none of the three configured gets a non-blocking "no policy
configured" skip. All deterministic failures (`vendor-constraints`,
`go mod verify`, `license-compliance`) are aggregated into one error, same as
`verify:`.

### `post:`

Runs after `policy:`, before Emit. The one stage that intentionally writes
into `--package-dir` rather than the scratch work dir -- for metadata that
needs to land in the tracked spec file, e.g. refreshing a generated
`Provides:` block from a vendored dependency manifest.

```yaml
post:
  - type: run
    artifacts: ["${PACKAGE}-${VERSION}.tar.gz"]
    command: ["./generate-bundled-provides.py", "${VERSION}"]
```

Each step's `command` runs with `--package-dir` as its working directory --
which is *not* where fetched/vendored artifacts live (they're in a scratch
work dir until Emit, which runs after Post). A step that needs to read one
declares its `output_name` in `artifacts:`; each is copied into
`--package-dir` under that name immediately before the command runs.

Skipped entirely under `--dry-run` (nothing should write to the real package
directory during a dry run) and when no `post:` steps are declared.

#### `bundled-provides` (built-in primitive)

The canonical `post:` case -- generating an RPM `Provides: bundled(npm(...))`
block for vendored JS dependencies -- is available as a built-in step, so no
custom script is needed. It parses the lockfile(s) in the fetched source tree
and writes one sorted `Provides:` line per dependency.

```yaml
post:
  - type: bundled-provides
    ecosystem: npm          # npm | pnpm | yarn
    modules:
      - path: "ui"          # defaults to [{ path: "." }]
    scope: production       # "production" (default, drops devDependencies) | "all"
    output: bundled-npm-provides.inc
```

It reads `package-lock.json` / `pnpm-lock.yaml` / `yarn.lock` from
`<source>/<module.path>` -- the same checkout `vendor`/`vendor-bump` operate
on, so the provides reflect any `vendor-bump` edits made earlier in the
pipeline. Versions are normalised to RPM form (a semver pre-release
`1.2.3-rc.1` becomes `1.2.3~rc.1`).

The namespace is deliberately fixed to `bundled(npm(<name>))` for **every** JS
ecosystem (npm/pnpm/yarn) and is not configurable. npm/pnpm/yarn all resolve
against the npm registry, so the package name is the stable identifier
regardless of which lockfile produced it. Unlike Go -- where
`go-rpm-macros` auto-generates `bundled(golang(...))` at build time from
`vendor/modules.txt` -- Fedora has no build-time generator for bundled npm
provides and no single blessed string, so gorget standardises on one form
(matching the Bundled Software Policy's `bundled(<system>(<name>))` shape).
Every gorget-packaged JS app emits the same namespace, keeping the block
greppable and consistent across packages.

The file is written into `--package-dir`; pull it into the spec with:

```spec
%include %{SOURCEN}    # e.g. %include %{S:9}, matching its SourceN: entry
```

Requires a preceding `git` fetch step to establish the source checkout; it
fails closed otherwise.

### `toolchain:`

```yaml
toolchain:
  - name: go        # one of: go, node, npm, cargo, rustc, python
    version: 1.22.0
```

Declares per-package tool version requirements for `vendor`/`vendor-bump`/
`build-ui`/`run` steps. **This currently only validates -- it never fetches
or switches versions.** Before any stage runs (even under `--dry-run`),
gorget checks the declared version against whatever's already installed
(e.g. `go version`), matching component-wise (`1.22` matches an installed
`1.22.3`), and fails closed on a mismatch or a missing tool. There is no
mechanism to actually *activate* a non-default version yet.

An earlier design shelled out to [`mise`](https://mise.jdx.dev/) to activate
an already-installed version on demand, but that was rejected: mise's job is
downloading toolchain binaries directly from their own upstream release
channels at runtime, which reintroduces exactly the kind of untrusted-source
problem gorget exists to eliminate for source tarballs, just one layer up.
The real mechanism needs to be RPM-native with zero mid-pipeline network
dependency (e.g. distinctly-named versioned binaries, the same pattern
Fedora already uses for `python3.9`/`python3.11`/`python3.12`) -- see
HUM-4990/HUM-4789 for the ongoing discussion.

## CLI flags

| Flag | Description |
|---|---|
| `--version` | New upstream version to fetch (required) |
| `--old-version` | Previous upstream version |
| `--dry-run` | Run through the Policy stage but skip Emit; prints the report to stdout instead |
| `--package-dir` | Package directory (default: `/package`) |
| `--pipeline-file` | Pipeline YAML file (default: `/pipeline.yaml`) |
| `--gpg-keys-dir` | GPG keys directory (default: `/gpg-keys`) |
| `--output-dir` | Output directory (default: `/output`) |
| `--upstream-repo` | Canonical upstream repo URL, exposed as `${UPSTREAM_REPO}` |
| `--debug` | Trace every stage/step transition and subprocess command run (argv, cwd, exit code, stdout/stderr) to stderr |

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Transient error (download failure, missing tool, invalid config) |
| 2 | Policy violation |

## Variable substitution

`${VERSION}`, `${VERSION_MAJOR}`, `${VERSION_MINOR}`, `${VERSION_PATCH}`,
`${OLD_VERSION}`, `${PACKAGE}`, `${SPEC_FILE}`, `${PACKAGE_DIR}`,
`${UPSTREAM_REPO}` are available in any string value in the pipeline YAML.

- `${PACKAGE_DIR}` is the absolute path to the package's directory (i.e.
  `--package-dir`) -- useful in `run:` step scripts that need to reach files
  living alongside the spec file, such as a patch applied before running a
  build tool.
- `${UPSTREAM_REPO}` is the value passed via `--upstream-repo`, if any --
  useful for pointing `type: git`'s `repo:` at the same canonical URL a
  caller already tracks elsewhere (e.g. its own package metadata), instead
  of duplicating it in the pipeline YAML. Empty string if not passed.

## Local development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

gorget --version 1.2.3 \
  --package-dir ./rpms/curl \
  --pipeline-file ./metadata/curl.source-pipeline.yaml \
  --output-dir /tmp/output \
  --dry-run

pytest
ruff check src/ tests/
mypy src/gorget
```

Tests that shell out to a real `rpmspec` are marked `integration` and are
skipped automatically when `rpmspec` isn't on `PATH`.

Run every example under `examples/` in one shot (sets up `.venv` if needed,
runs each demo's setup script, then runs gorget against each pipeline YAML):

```bash
./run-examples.sh
```
