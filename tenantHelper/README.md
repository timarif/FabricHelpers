# fabric-tenant

> Snapshot and compare **Microsoft Fabric admin tenant settings** across two physically
> different Fabric tenants (different Entra tenants, different logins) — with
> deterministic snapshots, risk-tiered diff, and an opt-in reporting lakehouse.

> **Status: alpha (Phase 1 scaffolding).** Tracking issue: [#44](https://github.com/timarif/FabricHelpers/issues/44).
> Auth + snapshot land in Phase 2; diff engine in Phase 3.

---

## Problem

Admins comparing tenant settings between (say) corp-test and corp-prod tenancies
today have to open two browsers side by side and scroll through hundreds of
settings looking for differences — focusing especially on the ones that affect
**data exfiltration** (Publish to web, Share with external users, Export to CSV,
SharePoint export, …).

The Fabric admin REST API exposes the settings programmatically, but the two
tenants need **two independent logins** — `fabric_core.auth.get_token` is
single-tenant on purpose (it derives the tenant from ambient context). This
helper adds an explicit multi-profile auth layer and a snapshot-then-diff
workflow on top.

---

## Install

```pwsh
pip install fabric-tenant
```

From source for development:

```pwsh
cd tenantHelper
pip install -e ".[dev]"
```

---

## Quick start (target shape — Phase 2+)

Create a profile file (`tenants.yaml`):

```yaml
profiles:
  prod:
    tenant_id: 11111111-1111-1111-1111-111111111111
    auth_mode: client_secret
    client_id: 22222222-2222-2222-2222-222222222222
    client_secret_env: FABRIC_PROD_SECRET   # only env-var NAMES allowed; loader rejects inline secrets
  test:
    tenant_id: 33333333-3333-3333-3333-333333333333
    auth_mode: device_code                  # human-in-the-loop second tenant
    client_id: 44444444-4444-4444-4444-444444444444
```

Snapshot each tenant:

```pwsh
fabric-tenant snapshot --profiles-file tenants.yaml --profile prod --out ./snapshots/prod.json
fabric-tenant snapshot --profiles-file tenants.yaml --profile test --out ./snapshots/test.json
```

Diff and render a markdown report:

```pwsh
fabric-tenant diff `
    --left  ./snapshots/prod.json `
    --right ./snapshots/test.json `
    --report-md   ./diff.md `
    --report-json ./diff.json `
    --prioritize-exfil-risk `
    --hide-equal
```

One-shot snapshot + diff:

```pwsh
fabric-tenant compare --profiles-file tenants.yaml `
                      --left-profile prod --right-profile test `
                      --report-md ./diff.md
```

---

## Design

- **Snapshot-then-diff.** Diff is a pure-local step on two JSON files — no live
  API calls — so it's safe to re-run, replay against historical snapshots
  (drift mode), and gate CI builds on.
- **Risk-tiered output.** Curated `EXFIL_RISK_CATALOG` (`PublishToWeb=95`,
  `AllowExternalDataSharingSwitch=90`, `AllowSendAOAIDataToOtherRegions=85`,
  `OneLakeForThirdParty=80`, `ExportToExcelSetting=70`, …) weights each
  diff. Markdown report has 🔴 / 🟡 / ⚪ sections; equal settings collapsed in
  `<details>`. Override via `--risk-catalog overrides.yaml`. See
  [`docs/api-reference.md`](docs/api-reference.md) for the verified setting catalog.
- **Two-tenant auth via profiles.** Per-profile `auth_mode`: `client_secret`,
  `device_code`, `interactive`, `managed_identity`, `azure_cli`. Each profile
  gets its own MSAL app with the right `authority=login.microsoftonline.com/{tenant_id}`.
- **Reporting lakehouse opt-in.** `--reporting-lakehouse` writes
  `fact_tenant_settings_diff` rows via the existing `fabric-reporting` adapter
  (matches the scanner/downloader pattern).

---

## Roadmap

| Phase | Status        | Deliverable                                                         |
| ----- | ------------- | ------------------------------------------------------------------- |
| 0     | ✅ this PR     | Sanitized API schema sample ([`docs/api-reference.md`](docs/api-reference.md)) |
| 1     | ✅ this PR     | Skeleton wheel + pyproject + CI wiring                              |
| 2     | ⏳ next        | Multi-profile auth + `fabric-tenant snapshot`                       |
| 3     | ⏳             | `normalize.py` + `diff.py` + `risk.py` + `fabric-tenant diff`       |
| 4     | ⏳             | `report/markdown.py` + `report/json_report.py`                      |
| 5     | ⏳             | One-shot `compare` + opt-in `fabric_reporting` adapter              |
| 6     | ⏳             | Notebook orchestrator + two-tenant auth setup guide                 |
| 7     | ⏳ (v2)        | Drift mode + delegated overrides (capacity / domain / workspace)    |
