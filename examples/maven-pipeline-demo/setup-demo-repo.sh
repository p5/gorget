#!/usr/bin/env bash
# Create a small Maven project with an old Commons Lang dependency.
set -euo pipefail
cd "$(dirname "$0")"

rm -rf demo-repo
mkdir demo-repo
cd demo-repo

cat > pom.xml <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>org.example</groupId>
  <artifactId>gorget-maven-demo</artifactId>
  <version>1.0.0</version>
  <dependencies>
    <dependency>
      <groupId>org.apache.commons</groupId>
      <artifactId>commons-lang3</artifactId>
      <version>3.12.0</version>
    </dependency>
  </dependencies>
</project>
EOF

git init -q -b main
git config user.email "demo@example.com"
git config user.name "Demo"
git add pom.xml
git commit -q -m "initial"
git tag v1.0.0

echo "Demo repo created at $(pwd), tagged v1.0.0"
