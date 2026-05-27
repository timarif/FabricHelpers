# Kusto Spark Connector — `commons-io` Shim for Fabric

## TL;DR

If you're trying to write to an Eventhouse/Kusto cluster from a Fabric Spark notebook and you hit:

```
java.lang.NoClassDefFoundError: kusto_connector_shaded/org/apache/commons/io/IOUtils
```

or later, after adding random JARs:

```
java.io.InvalidClassException: com.microsoft.kusto.spark.datasink.KustoWriteResource;
  local class incompatible:
  stream classdesc serialVersionUID = 2501697895925738687,
  local class serialVersionUID = -5982374439227749367
```

then you've hit a **Microsoft packaging defect** in the bundled Kusto Spark connector. The fix is a tiny shim JAR (~531 KB) that supplies the missing classes. This document explains why, and gives two ways to deploy it.

---

## The Problem

Fabric Spark runtimes **1.2 and 1.3** both pre-install **`kusto-spark 7.0.4`**. The Maven Central JAR for that version has a packaging defect: the `commons-io` library was **never bundled under its `kusto_connector_shaded.` prefix**, even though `KustoWriter` bytecode points at it.

In other words, the connector class files reference symbols like:

```
kusto_connector_shaded.org.apache.commons.io.IOUtils
```

…but those classes were never actually placed inside the published JAR. So at runtime — only on the write code path that touches IO buffers — the executor JVM tries to resolve the reference, fails, and throws `NoClassDefFoundError`.

This is **upstream Microsoft's bug**, not a Fabric-side bug, not a connector-version-selection bug, and not something a user can fix by upgrading or rolling back. The defect is present in **every** version of `kusto-spark` we tested on Maven Central, including the latest **7.0.6**.

### Why some write modes "work"

| Write mode | Code path | Affected? |
|---|---|---|
| `Transactional` (default) | Azure Storage SDK | ✅ Works — bypasses the broken code path |
| `Queued` | Azure Storage SDK | ✅ Works — bypasses the broken code path |
| `KustoStreaming` | Direct ingest via shaded IO | ❌ **Breaks** — hits the missing class |

If you've never seen this error, you've been using `Transactional` or `Queued`. The moment you switch to `KustoStreaming` (which you'd want for low-latency ingestion), the missing class blows up.

---

## The Fix — a "commons-io shim" JAR

The shim is a small JAR that contains exactly the missing classes:

- Source: **`commons-io 2.16.1`** from Maven Central
- Relocation: every `org.apache.commons.io.*` class is rewritten into the `kusto_connector_shaded.org.apache.commons.io.*` namespace using `maven-shade-plugin`
- Size: **~531 KB / 347 classes**
- Provides: `IOUtils`, `FileUtils`, `BoundedInputStream`, and the rest of `commons-io`, all under the namespace the connector's bytecode is looking for

When this JAR is on the classpath, `kusto-spark` finds the missing classes and the write path works as designed. You don't replace or shadow the connector — you just **supplement** it with the classes Microsoft forgot to bundle.

### ⚠️ Important: get the commons-io version right

We initially built the shim from `commons-io 2.13.0`. It got past the `NoClassDefFoundError` but then produced a **`serialVersionUID` mismatch on `KustoWriteResource`** between driver and executor. Microsoft's bundled `kusto-spark 7.0.4` was shaded against the `commons-io 2.16.x` API; mixing in 2.13 introduces subtly different class shapes that destabilize Spark's serialization handshake.

**Always build the shim from `commons-io 2.16.1`** (or whatever version Microsoft used at the time the runtime was published).

---

## Deployment Option A — Per-notebook (`%%configure`)

Use this when you want a quick, contained fix in one notebook. The config is reapplied on every session start.

1. Upload `kusto-commons-io-shim-1.0.0.jar` to a Lakehouse `Files/` folder you can address via `abfss://`.
2. Put this at the top of the notebook (replaces or overrides any existing session config):

```jsonc
%%configure -f
{
  "conf": {
    "spark.jars": "abfss://<workspace>@onelake.dfs.fabric.microsoft.com/<lakehouse>.Lakehouse/Files/kusto-commons-io-shim-1.0.0.jar",
    "spark.driver.userClassPathFirst":   "true",
    "spark.executor.userClassPathFirst": "true"
  }
}
```

3. Then write to Kusto normally:

```scala
val kustoUri    = "https://<your-cluster>.kusto.fabric.microsoft.com"
val database    = "<database>"
val tableName   = "<table>"
val accessToken = mssparkutils.credentials.getToken(kustoUri)

val df = spark.read
  .format("com.microsoft.kusto.spark.datasource")
  .option("accessToken",   accessToken)
  .option("kustoCluster",  kustoUri)
  .option("kustoDatabase", database)
  .option("kustoQuery",    s"['$tableName'] | take 10")
  .load()

df.write
  .format("com.microsoft.kusto.spark.datasource")
  .option("kustoCluster",  kustoUri)
  .option("kustoDatabase", database)
  .option("kustoTable",    tableName)
  .option("writeMode",     "KustoStreaming")   // ← the mode that needs the shim
  .option("accessToken",   accessToken)
  .mode("append")
  .save()
```

### Notes on Option A

- **Do NOT add `spark.driver.extraClassPath` / `spark.executor.extraClassPath`** entries with bare filenames. They don't resolve on executor filesystems and they're redundant with `spark.jars` (which both ships the JAR and adds it to the classpath).
- `userClassPathFirst=true` is required: it ensures the user-supplied shim wins the class load when the connector resolves the shaded namespace.
- `%%configure -f` re-creates the session; if anything seems stale, also use **Run → Stop session** and re-run the configure cell.

---

## Deployment Option B — Custom Environment (recommended for teams)

Use this when multiple notebooks need the shim, you want the config to survive workspace restarts, or you want to share it across users.

### Steps

1. **Workspace → New → Environment** → name it (e.g., `kusto-streaming-env`).
2. **Libraries → Custom libraries → Upload** → upload `kusto-commons-io-shim-1.0.0.jar`.
3. **Spark compute → Spark properties** → add:

   | Property | Value |
   |---|---|
   | `spark.driver.userClassPathFirst`   | `true` |
   | `spark.executor.userClassPathFirst` | `true` |

4. **Publish** the environment (takes 5–15 min the first time — Fabric bakes the JAR into the runtime image).
5. In the notebook: **top-right → Environment dropdown → kusto-streaming-env → restart session**.

That's the entire Environment config. **Do not** add a `spark.jars` entry — the uploaded JAR is auto-distributed to driver and every executor by the Environment itself.

The notebook write code is identical to Option A (no `%%configure` cell needed):

```scala
val kustoUri    = "https://<your-cluster>.kusto.fabric.microsoft.com"
val database    = "<database>"
val tableName   = "<table>"
val accessToken = mssparkutils.credentials.getToken(kustoUri)

df.write
  .format("com.microsoft.kusto.spark.datasource")
  .option("kustoCluster",  kustoUri)
  .option("kustoDatabase", database)
  .option("kustoTable",    tableName)
  .option("writeMode",     "KustoStreaming")
  .option("accessToken",   accessToken)
  .mode("append")
  .save()
```

### Side-by-side equivalence

| `%%configure` key | Environment location |
|---|---|
| `spark.jars: abfss://.../kusto-commons-io-shim-1.0.0.jar` | Libraries → Custom libraries → Upload |
| `spark.driver.userClassPathFirst: true` | Spark compute → Spark properties |
| `spark.executor.userClassPathFirst: true` | Spark compute → Spark properties |

---

## Verification

After the session starts (either Option A or B), run these in a Scala cell:

```scala
// 1) Shim's IOUtils is loadable
Class.forName("kusto_connector_shaded.org.apache.commons.io.IOUtils")
// res0: java.lang.Class[_] = class kusto_connector_shaded.org.apache.commons.io.IOUtils

// 2) Exactly one shim is on the user classpath (Fabric's bundled connector won't show here — it's on the system classpath)
spark.sparkContext.listJars()
  .filter(j => j.contains("kusto") || j.contains("commons-io-shim"))
  .foreach(println)
// expected: one line for kusto-commons-io-shim-1.0.0.jar

// 3) The streaming ingestion policy is enabled on the target table
//    Run in the Eventhouse / KQL query window once per table:
//    .alter table <YourTable> policy streamingingestion enable
```

If all three pass, the `KustoStreaming` write should succeed.

---

## Building the shim from scratch (optional)

If you need to rebuild it (e.g., Microsoft ships a new connector version and the missing-class set changes), the recipe is:

**`pom.xml`:**

```xml
<project xmlns="http://maven.apache.org/POM/4.0.0">
  <modelVersion>4.0.0</modelVersion>
  <groupId>com.microsoft.kusto.shim</groupId>
  <artifactId>kusto-commons-io-shim</artifactId>
  <version>1.0.0</version>
  <packaging>jar</packaging>

  <properties>
    <maven.compiler.source>11</maven.compiler.source>
    <maven.compiler.target>11</maven.compiler.target>
    <project.build.sourceEncoding>UTF-8</project.build.sourceEncoding>
  </properties>

  <dependencies>
    <dependency>
      <groupId>commons-io</groupId>
      <artifactId>commons-io</artifactId>
      <version>2.16.1</version>
    </dependency>
  </dependencies>

  <build>
    <plugins>
      <plugin>
        <groupId>org.apache.maven.plugins</groupId>
        <artifactId>maven-shade-plugin</artifactId>
        <version>3.5.0</version>
        <executions>
          <execution>
            <phase>package</phase>
            <goals><goal>shade</goal></goals>
            <configuration>
              <createDependencyReducedPom>false</createDependencyReducedPom>
              <shadedArtifactAttached>false</shadedArtifactAttached>
              <relocations>
                <relocation>
                  <pattern>org.apache.commons.io</pattern>
                  <shadedPattern>kusto_connector_shaded.org.apache.commons.io</shadedPattern>
                </relocation>
              </relocations>
            </configuration>
          </execution>
        </executions>
      </plugin>
    </plugins>
  </build>
</project>
```

Build with:

```powershell
mvn -B clean package
# output: target/kusto-commons-io-shim-1.0.0.jar  (~531 KB, 347 classes)
```

If a future runtime ships a different connector version that references missing classes from another shaded library (e.g., `commons-codec`, `commons-text`), add another `<relocation>` block following the same pattern, with the dependency added to the `<dependencies>` section.

---

## Troubleshooting matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| `NoClassDefFoundError: kusto_connector_shaded/org/apache/commons/io/IOUtils` | Shim not on classpath | Verify upload (Option A: `spark.jars` URL; Option B: JAR in Custom libraries). Restart session. |
| `InvalidClassException ... serialVersionUID` mismatch on `KustoWriteResource` | You also uploaded your own `kusto-spark.jar`, creating two versions | Remove your `kusto-spark.jar` from the Environment / `spark.jars`. Keep ONLY the shim. |
| Same UID mismatch with only the shim present | Wrong `commons-io` version in the shim (e.g., 2.13 vs 2.16) | Rebuild the shim from `commons-io 2.16.1`. |
| `Class.forName("kusto_connector_shaded...IOUtils")` throws ClassNotFoundException | Shim isn't on classpath at all (URL typo, upload failed) | Re-check the OneLake path / Environment upload. Inspect `spark.sparkContext.listJars()`. |
| Write succeeds but no data appears in the table | Streaming ingestion policy not enabled on the table | Run `.alter table <Table> policy streamingingestion enable` in KQL. |

---

## Why the shim, and not a workaround?

There are three alternatives, all worse:

1. **Switch to `writeMode=Transactional`** — works without any shim, but adds end-to-end latency (write to staging blob → trigger Kusto load → wait). Defeats the purpose of `KustoStreaming`.
2. **Use the Kusto Java SDK directly via `foreachPartition`** — bypasses the connector entirely, works fine, but you give up the connector's schema mapping, retries, and metrics. Code becomes more invasive.
3. **The shim** — minimal, surgical, the connector keeps doing its job, you keep `KustoStreaming`, and the fix is portable across notebooks and workspaces. ✅

---

## Acknowledgements

The packaging defect was diagnosed by inspecting the published `kusto-spark` JAR contents against the `KustoWriter` bytecode's referenced symbols. The shim approach was independently arrived at by Microsoft engineering after the same debugging journey. This repo's `kusto-commons-io-shim-1.0.0.jar` is byte-identical (at the class-file level) to the version that engineering produced.
