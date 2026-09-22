# More Gradle upstream checks

These pipelines exercise the Gradle backend against three real upstream
projects:

| Project | Ref | Build style |
|---|---|---|
| Mockito-Kotlin | `v6.3.0` | Kotlin DSL library |
| OkHttp | `parent-5.5.0` | Kotlin Multiplatform build |
| Gradle Versions Plugin | `v0.64.0` | Gradle plugin build |

Each pipeline runs the project's checked-in `./gradlew build` through gorget
and emits a source archive plus a Gradle user-home archive. Run these commands
from this directory:

```bash
gorget --version 6.3.0 \
  --package-dir mockito-kotlin \
  --pipeline-file mockito-kotlin/mockito-kotlin.source-pipeline.yaml \
  --output-dir /tmp/gorget-mockito-kotlin-output
```

The OkHttp and Gradle Versions Plugin commands use versions `5.5.0` and
`0.64.0`, respectively. These builds need a working JDK, network access for
the initial cache population, and enough disk space for their full builds.

The default Gradle task is `build`. Set `task` when the upstream project needs
another task. For example, use the distribution task for the Gradle source
tree:

```yaml
transform:
  - type: vendor
    ecosystem: gradle
    task: ":distributions-full:binDistributionZip"
```
