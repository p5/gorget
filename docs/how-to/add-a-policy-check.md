# How-to: add a policy check to an existing pipeline

You have a package that already has a working `*.source-pipeline.yaml` -- no
`policy:` section yet -- and you've been asked to guard against something
specific: a CVE in a vendored dependency, a license you don't want to ship, or
just "make sure a hand-applied fix doesn't silently disappear." This walks
through retrofitting a `policy:` block into that existing pipeline, rather
than explaining the schema from scratch (see the README's
[`policy:`](../../README.md#policy) section for the full reference, and
[`examples/policy-demo/`](../../examples/policy-demo/) for a runnable,
isolated simulation of the mechanism).

## 1. Pick the right check

| You want to... | Use |
|---|---|
| Confirm a vendored dependency is at least some version (e.g. the fix for a CVE) | `vendor-constraints` |
| Catch checksum/signature-verifiable regressions across the whole vendor tree | `audit` |
| Block a disallowed license from being vendored | `license-compliance` |

`vendor-constraints` is the one you'll reach for most -- it's what re-confirms
a fix actually took effect on every run, not just the run where someone
hand-patched a lockfile. The rest of this guide uses it as the worked example;
`audit` and `license-compliance` slot into the same `policy:` block (see the
README table for their exact behavior and caveats, e.g. `npm audit`/
`cargo audit` are warn-only, never fail-closed).

## 2. Find the pipeline's ecosystem

`vendor-constraints` needs to know which ecosystem's vendored copy to check
(`go`, `npm`, or `cargo`) -- look at the package's existing `fetch:` or
`transform:` steps for a `vendor`/`vendor-bump` step's `ecosystem:` field. For
example, `metadata/grafana12.4.source-pipeline.yaml` in the `rpms` repo has:

```yaml
fetch:
  - type: git
    repo: "${UPSTREAM_REPO}"
    ref: "v${VERSION}"
  - type: vendor
    ecosystem: go
    archive_name: "grafana-${VERSION}-vendor.tar.bz2"
```

`ecosystem: go` tells you `policy.vendor-constraints` entries for this
package should also say `ecosystem: go`.

## 3. Add the `policy:` block

Append a top-level `policy:` section to the existing pipeline YAML -- it
doesn't need to touch `fetch:`/`transform:`. To guard against a Go dependency
CVE regressing:

```yaml
policy:
  vendor-constraints:
    - package: golang.org/x/crypto
      ecosystem: go
      version: "0.31.0"
      reason: "CVE-2024-45337"
```

- `package` is the module/package path as it appears in `go list -m`
  (`node_modules/<pkg>/package.json` for npm, `Cargo.lock` for cargo).
- `version` is a **minimum** -- "at least this version," not an exact pin.
- `reason` is free text for the audit trail (CVE ID, ticket, etc.) -- it's not
  checked, just recorded in `report.json`.

Multiple entries are fine; every vendored module for the declared ecosystem is
checked automatically, so you don't need one entry per module unless you're
actually constraining more than one.

## 4. Test it locally before committing

Run gorget against a real checkout of the package with `--dry-run` first --
this runs through Policy but skips Emit, so nothing gets written:

```bash
gorget --version <current-version> \
  --package-dir /path/to/rpms/grafana12.4 \
  --pipeline-file /path/to/rpms/metadata/grafana12.4.source-pipeline.yaml \
  --upstream-repo https://github.com/grafana/grafana \
  --output-dir /tmp/gorget-check \
  --dry-run
```

Check the printed report for a `policy` stage entry. A passing constraint
looks like:

```json
{
  "type": "vendor-constraints",
  "target": "golang.org/x/crypto",
  "status": "passed",
  "reason": null
}
```

If the vendored version is actually below your declared minimum, the run
exits with code `2` (see the README's
[Exit codes](../../README.md#exit-codes) table) and prints the violation:

```
error: Policy violation (1 check(s)):
- [vendor-constraints] golang.org/x/crypto: golang.org/x/crypto is 0.29.0, need >= 0.31.0 (CVE-2024-45337)
```

That's the signal you're adding: today it should pass (you're constraining to
what's already vendored, or higher); the value comes from it catching a
*future* run that silently regresses.

## 5. Commit

Once the dry run passes, commit the YAML change same as any other pipeline
edit -- no code changes to gorget itself are needed for `vendor-constraints`,
`audit`, or `license-compliance`; they're all driven entirely by the YAML.
