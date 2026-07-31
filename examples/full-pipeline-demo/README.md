# Example: the "uber" pipeline (every primitive, one pipeline)

Runnable, non-pytest example exercising every stage of gorget's pipeline
together, kept up to date as new primitives are added -- if you add a new
step type or check, add it here too. It's a superset of
`../go-pipeline-demo` (all five Transform step types) with a Verify check
and a Policy check layered on top.

| Stage | Step | What it does here |
|---|---|---|
| Fetch | `git` | Clones `demo-repo/`, a real Go module |
| Fetch | `url` (×2) | Downloads GNU Hello's real tarball + its real detached GPG signature |
| Transform | `strip-tarball` | Removes `docs/` from the Go source tarball |
| Transform | `vendor-bump` | Bumps `rsc.io/quote` from `v1.0.0` to `v1.5.2` |
| Transform | `vendor` | Vendors the now-bumped dependency |
| Transform | `build-ui` | Runs `npm run build` in `ui/`, archives `dist/` |
| Transform | `run` | Escape hatch: runs `go version`, archives the output file |
| Verify | `gpg-signature` | Verifies GNU Hello's tarball against its real upstream maintainer key |
| Verify | *(implicit)* | Re-publication detection runs automatically since `sources` exists here |
| Policy | `vendor-constraints` | Confirms `vendor-bump`'s bump to `rsc.io/quote` actually took effect |

**Deliberately not included** (each already has its own focused, faster
example -- duplicating them here would just make this slower to run without
adding coverage): `spec-update`/`spec-source` fetch steps (see
`../spec-source-demo`), `checksum-file` verify (unit/dispatch-tested only,
no example yet), `audit:`/`license-compliance:` policy checks (see
`../policy-demo`).

Requires `git`, `go`, `npm`, and `gpg` on `PATH`, plus network access
(`proxy.golang.org`, `registry.npmjs.org`, `ftp.gnu.org`).

## 1. Set up the demo repo (once)

```bash
./setup-demo-repo.sh
```

Creates `demo-repo/`: a tiny real Go module pinned to an old
`rsc.io/quote v1.0.0`, a `docs/` dir to be stripped, and a minimal `ui/` npm
project for `build-ui`.

## 2. Run gorget

```bash
cd examples/full-pipeline-demo   # relative paths in the pipeline YAML resolve from here
source ../../.venv/bin/activate  # skip if gorget is already installed/on PATH

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-full-output
```

## 3. Inspect the result

```bash
ls /tmp/gorget-full-output

# strip-tarball: docs/ is gone from the Go source tarball
tar tzf /tmp/gorget-full-output/demo-main.tar.gz | grep docs   # <- prints nothing

# vendor-bump + vendor: rsc.io/quote bumped and actually vendored
tar tzf /tmp/gorget-full-output/demo-vendor.tar.gz | grep quote

# build-ui: the built dist/ output, archived
tar tzf /tmp/gorget-full-output/demo-ui-assets.tar.gz

# run: the escape-hatch command's declared output, archived verbatim
cat /tmp/gorget-full-output/go-version.txt

# every stage's status, every check's result, every artifact's checksum
cat /tmp/gorget-full-output/report.json
```

`report.json`'s `verify` and `policy` stages both show real, passing checks:

```json
{ "type": "gpg-signature", "target": "hello-2.12.1.tar.gz", "status": "passed", "reason": null }
{ "type": "vendor-constraints", "target": "rsc.io/quote", "status": "passed", "reason": null }
```

Re-run `./setup-demo-repo.sh` to reset `demo-repo/` back to its original
state before trying again.

## 4. See it fail closed

Bump the Policy constraint above what's actually vendored, simulating the
`vendor-bump` regression this check exists to catch
(see `../policy-demo/README.md` for the real incident):

```bash
sed -i 's/version: "1.5.2"/version: "9.9.9"/' demo.source-pipeline.yaml

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --gpg-keys-dir gpg-keys \
  --output-dir /tmp/gorget-full-output
echo "exit code: $?"

git checkout demo.source-pipeline.yaml   # revert
```

Exit code 2, `error: Policy violation (1 check(s)): - [vendor-constraints]
rsc.io/quote: rsc.io/quote is v1.5.2, need >= 9.9.9 (...)`.

## 5. `toolchain:` -- validates, doesn't fetch or switch

`demo.source-pipeline.yaml` has a commented-out `toolchain:` section near
the bottom. `setup-demo-repo.sh` prints your machine's actual installed
`go` version -- uncomment the section and paste that value in:

```yaml
toolchain:
  - name: go
    version: 1.25.10   # <- whatever setup-demo-repo.sh printed for you
```

Re-run step 2 and it passes: gorget checks the declared version against
whatever's already installed (`go version`) and matches component-wise, so
`1.25` matches an installed `1.25.10`. Change `version:` to something that
doesn't match (e.g. `1.22.0`) and it fails closed instead, before any stage
runs (even under `--dry-run`):

```
error: Required toolchain go@1.22.0 does not match the installed version
(1.25.10). gorget validates against whatever is already installed -- it
doesn't fetch or switch toolchain versions (see HUM-4990/HUM-4789).
```

That's the whole feature right now: a safety check against the ambient
environment, nothing more. An earlier design shelled out to `mise` to
actually *activate* arbitrary versions, but that was rejected as a
supply-chain trust violation (mise downloads toolchain binaries from their
own upstream release channels at runtime) -- see HUM-4990/HUM-4789 for the
real multi-version mechanism this will eventually grow into. Comment the
section back out (or match your real version) to get a working pipeline.
