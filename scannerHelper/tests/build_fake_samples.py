"""Build fake_samples.ipynb (and the extracted fake_samples.txt) used as a
regex fixture for the Fabric Notebook URL & Secret Scanner.

EVERY URL, GUID, KEY, TOKEN, PASSWORD, AND CONNECTION STRING WRITTEN BY THIS
SCRIPT IS FAKE. The strings are shaped to exercise the scanner's regex
patterns; none of them point at real resources or grant access to anything.

Usage:
    python build_fake_samples.py

Outputs (written next to this script):
    fake_samples.ipynb   - Jupyter notebook (intentionally never executed)
    fake_samples.txt     - flat text extraction of every cell source
"""

from __future__ import annotations

import json
from pathlib import Path


CELLS: list[tuple[str, str]] = []


def md(source: str) -> None:
    CELLS.append(("markdown", source))


def code(source: str) -> None:
    CELLS.append(("code", source))


# ---------------------------------------------------------------------------
# Cell 1 - disclaimer
# ---------------------------------------------------------------------------
md("""\
# Scanner Test Fixtures - ALL VALUES FAKE

> **DISCLAIMER:** Every URL, GUID, key, token, password, connection string,
> and credential in this notebook is **FAKE**. They exist only to exercise
> the regex patterns in `fabric_url_scanner.ipynb`. None of these values
> point at real resources or grant access to anything. Do **not** treat any
> string in this file as sensitive - they are deliberately published.

This notebook is intentionally **never executed**. It is a regex fixture
saved in `.ipynb` form so it can be fed straight into the scanner alongside
real notebooks during testing.
""")


# ---------------------------------------------------------------------------
# Cell 2 - fake GUIDs
# ---------------------------------------------------------------------------
code("""\
# All GUIDs below are FAKE - test placeholders only.
SOURCE_WORKSPACE_ID   = "00000000-0000-0000-0000-000000000001"  # FAKE
DEST_WORKSPACE_ID_A   = "00000000-0000-0000-0000-000000000002"  # FAKE
DEST_WORKSPACE_ID_B   = "11111111-2222-3333-4444-555555555555"  # FAKE
LAKEHOUSE_ID          = "deadbeef-dead-beef-dead-beefdeadbeef"  # FAKE
NOTEBOOK_ID           = "cafef00d-cafe-f00d-cafe-f00dcafef00d"  # FAKE
TENANT_ID             = "abcdef01-2345-6789-abcd-ef0123456789"  # FAKE
SUBSCRIPTION_ID       = "12345678-1234-1234-1234-123456789012"  # FAKE
DATASET_ID            = "aaaabbbb-cccc-dddd-eeee-ffffaaaa1111"  # FAKE
""")


# ---------------------------------------------------------------------------
# Cell 3 - fake write URLs across cloud storage schemes
# ---------------------------------------------------------------------------
code('''\
# All FAKE write URLs - none point to real resources.

# OneLake / Fabric ABFSS (cross-workspace write target - FAKE)
df.write.format("delta").save(
    "abfss://00000000-0000-0000-0000-000000000002@onelake.dfs.fabric.microsoft.com/"
    "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/Tables/fake_table"
)

# OneLake same-workspace write (FAKE)
df.write_delta(
    "abfss://00000000-0000-0000-0000-000000000001@onelake.dfs.fabric.microsoft.com/"
    "deadbeef-dead-beef-dead-beefdeadbeef/Tables/fake_local_table"
)

# OneLake read URL (FAKE, for direction-classification testing)
spark.read.parquet(
    "abfss://00000000-0000-0000-0000-000000000001@onelake.dfs.fabric.microsoft.com/"
    "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb/Files/fake_input.parquet"
)

# Azure Blob Storage write (FAKE)
df.write_delta("wasbs://fake-container@fakestorageaccount.blob.core.windows.net/fake/output/")
df.write.parquet("https://fakestorageaccount.blob.core.windows.net/fake-container/output/")

# Azure Data Lake Gen1 (FAKE)
df.write.save("adl://fakestore.azuredatalakestore.net/fake/path/")

# S3 (FAKE)
df.write.format("parquet").save("s3://fake-bucket/fake/key/")
df.to_csv("s3a://fake-bucket/fake.csv")
df.write.json("s3n://fake-bucket/json/")

# Google Cloud Storage (FAKE)
df.write.csv("gs://fake-bucket/fake-prefix/")

# HDFS / DBFS (FAKE)
df.write.delta("hdfs://fake-namenode:8020/fake/path/")
df.write_delta("dbfs:/fake/output/")

# FTP / file scheme (FAKE)
urlopen("ftp://fake.example.org/incoming/")
open("file:///tmp/fake.local", "wb")
''')


# ---------------------------------------------------------------------------
# Cell 4 - fake Fabric / Power BI REST write URLs
# ---------------------------------------------------------------------------
code('''\
# All FAKE REST URLs - none reach real services.
import requests

# Fabric REST API write (FAKE workspace - cross-workspace flow)
requests.post(
    "https://api.fabric.microsoft.com/v1/workspaces/"
    "00000000-0000-0000-0000-000000000002/items",
    json={"displayName": "fake_item"},
)

# Power BI dataset refresh (FAKE)
requests.post(
    "https://api.powerbi.com/v1.0/myorg/groups/"
    "11111111-2222-3333-4444-555555555555/datasets/"
    "aaaabbbb-cccc-dddd-eeee-ffffaaaa1111/refreshes"
)

# Fabric REST cross-workspace PUT (FAKE)
requests.put(
    "https://api.fabric.microsoft.com/v1/workspaces/"
    "00000000-0000-0000-0000-000000000003/lakehouses/"
    "deadbeef-dead-beef-dead-beefdeadbeef/tables/fake"
)

# ARM REST (FAKE subscription)
requests.patch(
    "https://management.azure.com/subscriptions/"
    "12345678-1234-1234-1234-123456789012/resourceGroups/fake-rg/"
    "providers/Microsoft.Storage/storageAccounts/fakestorageaccount"
    "?api-version=2023-01-01"
)

# Generic API DELETE (FAKE)
requests.delete("https://fakeapi.example.com/v1/items/42")
''')


# ---------------------------------------------------------------------------
# Cell 5 - fake secrets / keys (covers the scanner's SECRET_PATTERNS shapes)
# ---------------------------------------------------------------------------
code('''\
# Every secret below is FAKE. They match the scanner's regex SHAPE only and
# decode to nothing useful. Do not treat any string in this cell as sensitive.

# Azure Storage account key (FAKE - 88-char base64 shape)
storage_key = "FAKEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFAKE=="

# Azure Storage SAS token (FAKE)
sas = (
    "?sv=2024-01-01&ss=b&srt=co&sp=rwdlaciytfx"
    "&se=2099-12-31T00:00:00Z&st=2024-01-01T00:00:00Z"
    "&spr=https&sig=FAKEsignatureForTestingOnlyDoNotUse%3D"
)

# SQL Server password embedded in a connection string (FAKE)
sql_conn = (
    "Server=fake.database.windows.net;Database=fake_db;"
    "User Id=fakeuser;Password=FAKEpassword123!;"
)

# Cosmos DB key (FAKE - ~64-char base64 shape)
cosmos_key = "FAKECOSMOSKEYAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFAKEKEY=="

# Generic API key (FAKE)
api_key = "api_key=FAKE-api-key-value-for-testing-only-do-not-use-12345"

# AAD / app registration client secret (FAKE)
client_secret = "client_secret=FAKE~client-secret-value-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890"

# Azure Storage full connection string with AccountKey (FAKE)
azure_conn = (
    "DefaultEndpointsProtocol=https;AccountName=fakestorageaccount;"
    "AccountKey=FAKEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFAKE==;"
    "EndpointSuffix=core.windows.net"
)

# Bearer JWT (FAKE - 3 base64url segments separated by dots)
auth_header = (
    "Authorization: Bearer "
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJGQUtFIiwibmFtZSI6IkZBS0UgVEVTVCIsImlhdCI6MTUxNjIzOTAyMn0."
    "FAKEsignatureForTestingPurposesOnlyDoNotUse"
)

# Event Hub SAS connection string (FAKE)
eh_conn = (
    "Endpoint=sb://fake.servicebus.windows.net/;"
    "SharedAccessKeyName=fakeKey;"
    "SharedAccessKey=FAKEEventHubKeyForTestingPurposesAAAAAAAAAAA="
)

# OpenAI API key (FAKE - sk- prefix + 48 chars)
openai_key = "sk-FAKEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFAKE"

# Spark account-key config (FAKE)
spark.conf.set(
    "fs.azure.account.key.fakestorageaccount.dfs.core.windows.net",
    "FAKEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFAKE==",
)

# JDBC URL with embedded password (FAKE)
jdbc_url = (
    "jdbc:sqlserver://fake.database.windows.net:1433;"
    "database=fake_db;user=fakeuser;password=FAKEjdbcPassword123!;"
)

# Generic secret= catch-all (FAKE)
generic = "secret=FAKEgenericSecretValueForTestingOnly12345"
''')


# ---------------------------------------------------------------------------
# Cell 6 - fake write-call samples (destination built at runtime)
# ---------------------------------------------------------------------------
code('''\
# Runtime-built destinations - all FAKE. These exercise the write-call
# detector for cases where no URL literal exists at the call site.

output_root = (
    f"abfss://{DEST_WORKSPACE_ID_A}@onelake.dfs.fabric.microsoft.com/"
    f"{LAKEHOUSE_ID}/Tables"
)

# Spark / pandas / polars writes
df.write_delta(f"{output_root}/fake_runtime_table")
df.write.mode("overwrite").saveAsTable("fake.staging.fake_table")
df.write.parquet(f"{output_root}/fake_pq")
df.write.format("delta").save(f"{output_root}/fake_delta")
df.to_parquet("/tmp/fake.parquet")
df.to_csv("/tmp/fake.csv")

# requests with runtime-built URL (FAKE)
endpoint = "https://fakeapi.example.com/v1/items"  # FAKE
requests.post(endpoint, json={"k": "v"})
requests.put(endpoint, json={"k": "v"})
requests.patch(endpoint, json={"k": "v"})
requests.delete(endpoint)

# Cloud SDK writes (FAKE)
s3_client.put_object(Bucket="fake-bucket", Key="fake/key", Body=b"x")
blob_client.upload_blob(b"x")

# Raw file writes
with open("/tmp/fake.bin", "wb") as f:
    f.write(b"x")

# SQL inserts (FAKE)
spark.sql("INSERT INTO fake_schema.fake_target SELECT * FROM fake_source")
spark.sql("INSERT OVERWRITE TABLE fake_schema.fake_overwrite SELECT * FROM fake_src")

# Structured Streaming write (FAKE)
(df.writeStream
   .format("delta")
   .outputMode("append")
   .option("checkpointLocation", f"{output_root}/_chk")
   .start(f"{output_root}/fake_stream"))
''')


# ---------------------------------------------------------------------------
# Cell 7 - URLs embedded in markdown (markdown source kind)
# ---------------------------------------------------------------------------
md("""\
## More fake URLs in markdown

These should be picked up by the scanner with `source_kind = "markdown"`.
All values are **FAKE**.

- App workspace link: `https://app.fabric.microsoft.com/groups/00000000-0000-0000-0000-000000000002/`
- Power BI report (FAKE): `https://app.powerbi.com/groups/11111111-2222-3333-4444-555555555555/reports/aaaabbbb-cccc-dddd-eeee-ffffaaaa1111`
- External docs (FAKE): `https://fakedocs.example.com/`
- FTP (FAKE): `ftp://fake.example.org/incoming/`
- File scheme (FAKE): `file:///tmp/fake.txt`
- ADL (FAKE): `adl://fakestore.azuredatalakestore.net/fake/path/`
""")


# ---------------------------------------------------------------------------
# Assemble notebook + text extraction
# ---------------------------------------------------------------------------
def build_notebook() -> dict:
    nb_cells = []
    for kind, src in CELLS:
        # Jupyter convention: source is a list of lines, each line ending in
        # "\n" except possibly the last.
        lines = src.splitlines(keepends=True)
        cell: dict = {
            "cell_type": kind,
            "metadata": {},
            "source": lines,
        }
        if kind == "code":
            cell["execution_count"] = None
            cell["outputs"] = []
        nb_cells.append(cell)

    return {
        "cells": nb_cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def build_text() -> str:
    out: list[str] = []
    out.append("# Scanner Test Fixtures - ALL VALUES FAKE\n")
    out.append("# Extracted from fake_samples.ipynb. Every URL/GUID/key/token/\n")
    out.append("# password/connection string below is FAKE.\n\n")
    for i, (kind, src) in enumerate(CELLS, 1):
        out.append(f"# ===== Cell {i} ({kind}) =====\n")
        out.append(src)
        if not src.endswith("\n"):
            out.append("\n")
        out.append("\n")
    return "".join(out)


def main() -> None:
    here = Path(__file__).resolve().parent
    nb_path = here / "fake_samples.ipynb"
    txt_path = here / "fake_samples.txt"

    nb_path.write_text(json.dumps(build_notebook(), indent=1) + "\n", encoding="utf-8")
    txt_path.write_text(build_text(), encoding="utf-8")

    print(f"wrote {nb_path}")
    print(f"wrote {txt_path}")


if __name__ == "__main__":
    main()
