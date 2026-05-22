# FabricHelpers

A collection of miscellaneous helpers for [Microsoft Fabric](https://www.microsoft.com/microsoft-fabric)
— self-contained notebooks and scripts that solve specific tenant-administration,
auditing, and operational problems we've hit in the wild.

Each helper lives in its own folder with its own README. The helpers are
independent — pick the one you need.

---

## Helpers

### 🔍 [`scannerHelper/`](./scannerHelper) — Fabric Notebook URL & Secret Scanner

A scalable Fabric / Spark notebook that audits every notebook in your tenant
for **URLs, hardcoded secrets, write operations, and cross-workspace data
flows**. Tested against tenants with 10,000+ workspaces and 18,000+ notebooks.

For every notebook it can read, the scanner flags:

- **URL literals** — every `https://`, `abfss://`, `wasbs://`, `s3://`, etc.,
  classified as `read` / `write` / `read_write` / `reference`.
- **Cross-workspace data flows** — destination workspace parsed out of OneLake
  / Fabric REST / Power BI URLs.
- **Hardcoded secrets** — 15 regex patterns (storage keys, SAS tokens, SQL
  passwords, Cosmos keys, API keys, client secrets, bearer JWTs, OpenAI keys,
  JDBC passwords, etc.). Match snippets are auto-redacted.
- **Potential writes** — destination-agnostic write API calls
  (`df.write_delta(...)`, `requests.post(...)`, `INSERT INTO …`, etc.) that
  catch notebooks writing to runtime-built destinations.

Runs in two modes: **API mode** (Fabric admin scanner / user-scoped APIs with
async aiohttp fanout) or **Lakehouse mode** (pre-exported `.ipynb` files,
10–100× faster). Results land in a single flat Delta table.

See [`scannerHelper/README.md`](./scannerHelper/README.md) for full setup,
configuration, output schema, and sample queries.

---

### 🔐 [`mpeHelper/`](./mpeHelper) — Fabric Managed Private Endpoint Manager

A Fabric notebook (`mpe_manager.ipynb`) that gives you a safe, auditable,
end-to-end lifecycle for **Managed Private Endpoints (MPEs)** across one or
more Fabric workspaces:

```
INVENTORY  →  DRY-RUN  →  DELETE  →  RECREATE  →  APPROVE
```

Every step is gated by an explicit flag, capped by a hard limit, and persisted
to a Delta audit table — so nothing destructive happens by accident and you
always have a paper trail.

- **Inventory** every MPE the caller can see across selected workspaces.
- **Dry-run** filters to preview which MPEs would be deleted (refuses if
  matches exceed `MAX_DELETES`).
- **Delete** only when `COMMIT=True`, with every HTTP response logged.
- **Recreate** MPEs from the most-recent delete-audit or any prior inventory
  snapshot, stamping each `requestMessage` with a run marker.
- **Approve** the resulting Pending Private Endpoint Connections on the Azure
  side via the ARM REST API, matched by the run marker.

A standalone CLI variant covers inventory + delete for workstation use without
Spark.

See [`mpeHelper/README_mpe.md`](./mpeHelper/README_mpe.md) for full
configuration, cell-by-cell architecture, and safety semantics.

---

## License

See [LICENSE](./LICENSE).
