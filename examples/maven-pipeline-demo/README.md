# Example: Maven bump and offline vendor repository

This example fetches a Maven project that uses Commons Lang 3.12.0. The
`vendor-bump` step changes it to 3.14.0. Gorget repacks the source archive,
creates an offline Maven repository, and checks the resolved version.

The example requires `git` and `mvn` on `PATH`. It also needs network access
when Gorget downloads the Maven dependencies.

## Run the example

```bash
./setup-demo-repo.sh

gorget --version 1.0.0 \
  --package-dir . \
  --pipeline-file demo.source-pipeline.yaml \
  --output-dir /tmp/gorget-maven-output \
  --debug
```

## Check the output

The source archive contains the new POM version:

```bash
tar xOf /tmp/gorget-maven-output/demo-1.0.0.tar.gz \
  demo-1.0.0/pom.xml | grep '<version>3.14.0</version>'
```

The vendor archive contains Commons Lang 3.14.0:

```bash
tar tzf /tmp/gorget-maven-output/demo-1.0.0-vendor.tar.gz | \
  grep 'commons-lang3/3.14.0/commons-lang3-3.14.0.jar'
```

Test the repository without network access:

```bash
mkdir -p /tmp/gorget-maven-build
tar xzf /tmp/gorget-maven-output/demo-1.0.0.tar.gz \
  -C /tmp/gorget-maven-build --strip-components=1
tar xzf /tmp/gorget-maven-output/demo-1.0.0-vendor.tar.gz \
  -C /tmp/gorget-maven-build
mvn -o -f /tmp/gorget-maven-build/pom.xml \
  -Dmaven.repo.local=/tmp/gorget-maven-build/vendor package
```

No RPM patch is necessary. PR #31's dirty-source mechanism repacks `Source0`
after `vendor-bump` changes `pom.xml`.
