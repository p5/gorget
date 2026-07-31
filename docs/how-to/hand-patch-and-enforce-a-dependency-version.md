# How-to: hand-patch a vendored dependency, and stop it from regressing

You found a CVE (or other bug) fixed in a newer release of something your
package vendors, and need to do two separate things: ship the fix *now*, and
make sure a later automated update can't silently undo it. `transform:
vendor-bump` does the first; `policy: vendor-constraints` does the second.
They're easy to conflate since both take a package name and a version, but
they run at different times for different reasons.

## The two parts

| | `transform: vendor-bump` | `policy: vendor-constraints` |
|---|---|---|
| Runs | Once, before the `vendor` step re-vendors | Every run, after everything's fetched |
| Does | Edits the dependency manifest/lockfile (`go.mod`, `package.json`, `Cargo.toml`) to require at least the given version | Reads back the *actually vendored* version and compares it against the declared minimum |
| Answers | "Bump this dependency before vendoring" | "Did the bump actually take, and does it still hold on every future run?" |

`vendor-bump` alone fixes this release. Nothing stops a later upstream update
from reverting the pin's edit (a fresh `go.mod`/`package.json` from upstream
won't have your hand-added minimum) and silently re-vendoring the vulnerable
version. `vendor-constraints` is what catches that: it doesn't care how the
vendored version got there, it just fails closed if it's ever below the
minimum again.

## 1. Bump it now

```yaml
transform:
  - type: vendor-bump
    ecosystem: go
    pins:
      - dependency: "golang.org/x/net"
        version: "0.23.0"     # >= 0.23.0
  - type: vendor
    ecosystem: go
```

The `version` field supports two constraint modes:

- **Plain version** (e.g. `"0.23.0"`): minimum, meaning `>=0.23.0`
- **Tilde prefix** (e.g. `"~4.18"`): pin to that prefix, meaning latest `4.18.x`

```yaml
pins:
  - dependency: "golang.org/x/text"
    version: "0.39.0"    # >= 0.39.0
  - dependency: "lodash"
    version: "~4.18"     # latest 4.18.x
```

`vendor-bump` must come before the `vendor` step, and both belong in
`transform:` (not `fetch:`) even though `vendor` is also a valid `fetch:`
step type elsewhere -- `fetch:` always runs before `transform:`, so this is
the only ordering that lets the pin's edit land before vendoring reads it.
See [`go-pipeline-demo`](../../examples/go-pipeline-demo/) for this running
against a real `go.mod`.

**For the `go` ecosystem, you also need a spec patch.** `fetch: {git}`
archives `Source0` from the checkout *before* `vendor-bump` edits `go.mod` in
that same checkout -- the edit only ever reaches the vendor archive, never
the plain source tarball. Without a spec patch replicating the same
`go.mod`/`go.sum` change onto the actual build tree, the build tree and the
vendor archive end up requiring different versions of the same dependency,
which `go build -mod=vendor` rejects as inconsistent vendoring. gorget
checks for this and fails closed (`GorgetConfigError`) before `vendor-bump`
mutates anything if no declared spec patch touches `go.mod`/`go.sum` --
compute that patch offline the same way you would for a CVE backport
(`go mod edit`/`go mod tidy` against a pristine clone), since Konflux builds
are hermetic and `%prep` can't re-run those commands itself. This is exactly
what broke `trivy` for real, via the equivalent `go-vendor-tools.toml`
`pre_commands` mechanism -- see `gorget/fetch/vendor/gomod_patch_sync.py`'s
module docstring for the full mechanism, which is identical for both.

## 2. Enforce it forever

```yaml
policy:
  vendor-constraints:
    - package: golang.org/x/net
      ecosystem: go
      version: "0.23.0"
      reason: "CVE-2024-XXXXX"
```

This is a completely independent check -- it re-resolves the actually
vendored version (`go list -m`, `node_modules/<pkg>/package.json`, or
`Cargo.lock`, depending on `ecosystem`) on every single run and compares it
against `version`, regardless of whether that version got there via your
`vendor-bump` step, a manually-edited lockfile, or upstream just happening to
require it already. See
[Add a policy check to an existing pipeline](add-a-policy-check.md) for more
on this section, and
[`policy-demo`](../../examples/policy-demo/) for a runnable simulation of the
regression this is designed to catch.

## Do you need both?

- **Fixing a CVE and want it to stick**: both. `vendor-bump` does the bump,
  `vendor-constraints` makes sure it can't quietly disappear later.
- **Someone already hand-edited the lockfile in a previous commit**: just
  `vendor-constraints` -- there's nothing left to bump, only to keep
  enforced.
- **A one-time bump you're confident upstream will carry forward on its
  own** (e.g. bumping to match a new upstream release that already requires
  the fixed version): `vendor-bump` alone is enough; add
  `vendor-constraints` later if you ever see it regress.

## Test locally

```bash
gorget --version <current-version> \
  --package-dir /path/to/your/package \
  --pipeline-file /path/to/your/package/pipeline.yaml \
  --output-dir /tmp/gorget-output \
  --dry-run
```

Check `report.json`'s `transform` stage for the pin taking effect, and
`policy` stage's `vendor-constraints` check for a `"status": "passed"`
entry. See the README's [Exit codes](../../README.md#exit-codes) table --
a regression here is a policy violation, exit `2`.
