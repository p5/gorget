# Kafka Gradle vendoring example

This example clones Apache Kafka 4.3.1, runs its full Gradle `build` task, and
archives the populated Gradle user home as a separate vendor artifact.

Kafka's repository includes the Gradle wrapper. The pipeline therefore uses
`./gradlew`, and the backend stores the wrapper distribution and dependency
cache under `vendor/`. A later build can extract that artifact and run
`GRADLE_USER_HOME=vendor ./gradlew --offline build`.

The Gradle backend runs `build` by default. Set the vendor step's `task` field
when an upstream project needs a different task.

The build needs Java 17 or 25, network access for the initial vendoring run,
and enough disk space for Kafka's full build and Gradle cache. The offline run
must use the same Kafka source tree and a compatible Gradle version.

Run it from this directory:

```bash
gorget --version 4.3.1 \
  --package-dir . \
  --pipeline-file kafka.source-pipeline.yaml \
  --output-dir /tmp/gorget-kafka-output
```

The output contains:

```text
kafka-4.3.1.tar.gz
kafka-4.3.1-gradle-vendor.tar.gz
report.json
```

To check the vendored cache against the source archive:

```bash
mkdir /tmp/kafka-offline
tar -xzf /tmp/gorget-kafka-output/kafka-4.3.1.tar.gz -C /tmp/kafka-offline
tar -xzf /tmp/gorget-kafka-output/kafka-4.3.1-gradle-vendor.tar.gz \
  -C /tmp/kafka-offline/kafka-4.3.1
cd /tmp/kafka-offline/kafka-4.3.1
GRADLE_USER_HOME=vendor ./gradlew --offline build
```
