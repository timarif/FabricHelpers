# Environment — setup guide

This folder contains the configuration-as-code for a Fabric Custom Environment that
makes `writeMode=KustoStreaming` work on Fabric Spark runtimes 1.2 / 1.3.

For *why* this is needed, see [`../README.md`](../README.md).

---

## Files

| File | Purpose |
|---|---|
| `environment.yml`  | Library manifest — lists the shim JAR that must be uploaded. |
| `Sparkcompute.yml` | Spark properties — `userClassPathFirst` on driver + executor. |

Custom JAR binaries can't be declared in YAML in Fabric; they must be uploaded
separately. The YAML serves as documented intent for code review.

---

## Setup — via the UI (recommended for first time)

1. **Workspace → New → Environment** → name it `kusto-streaming-env`.
2. **Libraries → Custom libraries → Upload** → upload `kusto-commons-io-shim-1.0.0.jar`.
3. **Spark compute → Spark properties** → add:

   | Property | Value |
   |---|---|
   | `spark.driver.userClassPathFirst`   | `true` |
   | `spark.executor.userClassPathFirst` | `true` |

4. Click **Publish**. First build takes 5–15 min.
5. Open one of the notebooks in [`../notebooks/`](../notebooks) and attach the
   environment via the **Environment** dropdown (top-right).

---

## Setup — via the Fabric REST API (for CI / repeatable deploys)

Get an Entra token and your workspace ID, then:

```powershell
# 1) Create the empty environment
$workspaceId = "<your-workspace-id>"
$token = (az account get-access-token --resource "https://api.fabric.microsoft.com" | ConvertFrom-Json).accessToken

$body = @{
  displayName = "kusto-streaming-env"
  description = "Ships kusto-commons-io shim for writeMode=KustoStreaming on runtimes 1.2/1.3"
} | ConvertTo-Json

$env = Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.fabric.microsoft.com/v1/workspaces/$workspaceId/environments" `
  -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
  -Body $body

$envId = $env.id

# 2) Upload the shim JAR as a custom library
$jar = "C:\path\to\kusto-commons-io-shim-1.0.0.jar"
curl.exe -X POST `
  -H "Authorization: Bearer $token" `
  -F "file=@$jar" `
  "https://api.fabric.microsoft.com/v1/workspaces/$workspaceId/environments/$envId/staging/libraries"

# 3) Set the Spark compute properties (from this folder's Sparkcompute.yml)
$sparkConfBody = @{
  sparkProperties = @{
    "spark.driver.userClassPathFirst"   = "true"
    "spark.executor.userClassPathFirst" = "true"
  }
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Patch `
  -Uri "https://api.fabric.microsoft.com/v1/workspaces/$workspaceId/environments/$envId/staging/sparkcompute" `
  -Headers @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" } `
  -Body $sparkConfBody

# 4) Publish the staging changes
Invoke-RestMethod `
  -Method Post `
  -Uri "https://api.fabric.microsoft.com/v1/workspaces/$workspaceId/environments/$envId/staging/publish" `
  -Headers @{ Authorization = "Bearer $token" }
```

Publish runs asynchronously — poll the `publishDetails` endpoint until `state == "Success"`.

---

## Verification

Open [`../notebooks/01-spark-to-kusto-with-environment.ipynb`](../notebooks/01-spark-to-kusto-with-environment.ipynb),
attach the environment, restart the session, and run the verification cell:

```scala
Class.forName("kusto_connector_shaded.org.apache.commons.io.IOUtils")

spark.sparkContext.listJars()
  .filter(j => j.contains("kusto") || j.contains("commons-io-shim"))
  .foreach(println)
```

If both succeed, the environment is ready and the write cell should complete.
