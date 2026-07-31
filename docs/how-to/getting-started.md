# Getting started: write your first `source-pipeline.yaml`

You have a package with no `*.source-pipeline.yaml` yet and need to add one.
This walks through the minimum viable pipeline and how to grow it, rather
than the full schema reference (see the README's
[Pipeline steps](../../README.md#pipeline-steps) section for that, and
[`examples/`](../../examples/) for runnable, hands-on versions of everything
below).

## 1. Check whether you need one at all

If your package's sources are just its spec file's `Source0`/`SourceN` URLs,
with nothing to clone, vendor, transform, or verify beyond that, **you might
not need a pipeline YAML**: gorget falls back to fetching every declared
`Source` URL when `--pipeline-file` points at a file that doesn't exist.
That's it -- no YAML to write or maintain.

You need a real pipeline YAML as soon as any of these apply:

- Sources come from a `git` clone rather than a tarball URL
- You need a vendor archive (Go/npm/pnpm/yarn/Cargo/Composer dependencies)
- Something needs transforming after fetch (stripping paths, building UI
  assets, running an arbitrary command)
- You want a checksum/signature check that isn't just the automatic
  re-publication guard (see below)
- You want a policy check (CVE version floor, license compliance, audit)

**Packaging a native project with no Fedora dist-git history?** All of the
above assumes you're starting from a spec that already has a real `Source0`
tarball URL to fall back to or add a check against. A brand-new native
package has no such URL -- there's nothing upstream ever published as a
tarball, so `fetch: git` (or another real fetch step) is mandatory rather
than one option among several: there's no bare-`spec-source` fallback the
way an already-Fedora-derived package has. `fetch: vendor` is a separate
question -- add it only if the package actually has dependencies to vendor,
exactly the same condition as for any package, native or not.
(`transform:`/`verify:`/`policy:`/`post:` are all still available too, if
your package needs them -- being native only forces `fetch:`, nothing else.)
See [`native-cargo-demo`](../../examples/native-cargo-demo/) for a native
package that happens to need both `git` and `vendor`, including a gotcha
specific to it: `%prep`'s `%autosetup -n` has to match the *archive's*
internal directory name (which
gorget derives from `archive_name`), not the upstream repo's own directory
naming.

## 2. Start from the smallest real pipeline

The simplest real pipeline still declares `fetch:` explicitly -- e.g. to add
a signature check for the tarball, alongside the spec-driven download. This
is [`examples/spec-source-demo`](../../examples/spec-source-demo/)'s
pipeline for GNU Hello, the traditional RPM-packaging "hello world":

```yaml
fetch:
  - type: spec-update
    reset-release: "1"

  - type: spec-source
    index: 0

  - type: url
    url: "https://ftp.gnu.org/gnu/hello/hello-${VERSION}.tar.gz.sig"
    filename: "hello-${VERSION}.tar.gz.sig"
```

- `spec-update` resets `Release:` before Source URLs resolve -- always edits
  a writable copy of the spec, never `--package-dir` itself.
- `spec-source` downloads `Source0:`, with `%{version}` macro-resolved
  against whatever `--version` you pass.
- `url` fetches something not declared in the spec at all -- here, the
  tarball's detached signature, so a later `verify: gpg-signature` step (or a
  hand-added one, see step 4) has something to check against.

That's a complete, valid pipeline. Run `examples/spec-source-demo` yourself
(its README has the exact commands) to see it fetch a real tarball before
adapting it to your own package.

## 3. Test it locally

```bash
gorget --version <current-version> \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --output-dir /tmp/gorget-output \
  --dry-run
```

`--dry-run` runs through every declared stage but skips Emit, printing the
report to stdout instead of writing files -- the safe way to iterate on a new
pipeline. Once it looks right, drop `--dry-run` and check
`/tmp/gorget-output/report.json` and the fetched artifacts.

An exit code of `0` means success; see the README's
[Exit codes](../../README.md#exit-codes) table for what `1` (transient
error -- bad config, download failure, missing tool) and `2` (policy
violation) mean.

## 4. Grow it as you need more

| You need to... | Add | See |
|---|---|---|
| Clone a git repo instead of downloading a tarball | `fetch: git` | [`go-pipeline-demo`](../../examples/go-pipeline-demo/), or [`native-cargo-demo`](../../examples/native-cargo-demo/) for the minimal git-only case |
| Vendor Go/npm/pnpm/yarn/Cargo/Composer dependencies | `fetch: vendor` | [`go-pipeline-demo`](../../examples/go-pipeline-demo/) (Go), [`native-cargo-demo`](../../examples/native-cargo-demo/) (Cargo) |
| Clone a *private* repo | `fetch: git` + ambient git auth | [Fetch from a private git repo](fetch-from-a-private-repo.md) |
| Strip paths from a fetched tarball, build UI assets, pack an explicit file list into an archive, or run an arbitrary command | `transform:` | README [`transform:`](../../README.md#transform) |
| Verify a GPG signature or a checksums-listing file | `verify:` | [`verify-demo`](../../examples/verify-demo/) |
| Enforce a dependency version floor, license, or audit result | `policy:` | [Add a policy check to an existing pipeline](add-a-policy-check.md) |
| Refresh generated metadata (e.g. a `Provides:` block) after everything else has run | `post:` | README [`post:`](../../README.md#post) |

[`full-pipeline-demo`](../../examples/full-pipeline-demo/) exercises every
one of these together in a single pipeline, kept up to date as new step types
are added -- useful as a reference once you're combining more than one or two
sections.
