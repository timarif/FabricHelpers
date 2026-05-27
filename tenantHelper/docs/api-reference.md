# Fabric Admin Tenant Settings — API Reference
<!-- tenantHelper/docs/api-reference.md -->
<!-- Phase 0 reference document for the fabric-tenant comparison helper -->

---

## 1. Endpoint Reference

### URL and method

```
GET https://api.fabric.microsoft.com/v1/admin/tenantsettings
```

### GA / Preview status

The **List Tenant Settings** operation is **Generally Available (GA)** as of the current v1 API surface.
The three delegated-override listing operations described in Section 4 are each explicitly marked
**Preview** ("This API is part of a Preview release and is provided for evaluation and development
purposes only.").

> Source: [learn.microsoft.com — List Tenant Settings](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings)

### Required role

The caller must be a **Fabric administrator** (also accepted: a service principal in an
admin-enabled security group — see Section 5).

> Source: [learn.microsoft.com — List Tenant Settings § Permissions](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings)

### Required delegated scopes

`Tenant.Read.All` **or** `Tenant.ReadWrite.All`

These scopes live under the **Power BI Service** resource (`https://api.fabric.microsoft.com`)
in the Azure portal app-registration permissions blade.

> Source: [learn.microsoft.com — List Tenant Settings § Required Delegated Scopes](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings)

### Pagination

The endpoint **does support pagination** via a continuation-token pattern.

| Parameter / field | Location | Description |
|---|---|---|
| `continuationToken` | Query string (optional) | Pass the token returned in a previous response to fetch the next page. |
| `continuationToken` | Response body | Token for the next page; **absent** when no further records exist. |
| `continuationUri` | Response body | Fully-formed URL for the next page; **absent** when no further records exist. |

In practice, a fresh tenant typically returns all ~100–140 settings in a single page and the
continuation fields are absent; the token mechanism is there for correctness.

> Source: [learn.microsoft.com — List Tenant Settings](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings);
> structure confirmed in `TenantSettings` object definition on the same page.

### Rate limits

Microsoft publishes an explicit limit of **25 requests per minute** for this endpoint family.
Exceeding it yields HTTP **429 Too Many Requests**. The response includes a `Retry-After` header
(integer seconds) indicating how long the client must wait before retrying.

```
HTTP/1.1 429 Too Many Requests
Retry-After: 12
```

> Source: [learn.microsoft.com — List Tenant Settings § Limitations](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings)

---

## 2. Response JSON Schema — Sanitized Realistic Example

### ⚠️ Conflict note — response envelope key

The **official Microsoft Docs** and the **official Swagger spec**
(`microsoft/mcp:tools/Fabric.Mcp.Tools.Docs/src/Resources/fabric-rest-api-specs/contents/admin/swagger.json`)
both define the envelope key as **`"value"`**.  
Real-world GitHub samples (`NatVanG/fab-inspector:DocsExamples/Sample-TenantSettings.json`,
`bidgeir/Mastering-Fabric-Administration:Extra/AdminSettings.json`) use **`"tenantSettings"`** as
their outer key.  
These samples appear to use an internal or older wrapper; the authoritative Fabric REST API shape
is `"value"`. Callers should handle both keys defensively if consuming data from mixed sources.

### Representative response (7 entries)

```json
{
  "value": [

    // ── 1. Simple boolean toggle, enabled tenant-wide, no security-group scoping ──────────────
    {
      "settingName": "PublishToWeb",
      "title": "Publish to web",
      "enabled": true,
      "canSpecifySecurityGroups": true,
      "tenantSettingGroup": "Export and sharing settings",
      "properties": [
        {
          "name": "CreateP2w",
          "value": "true",
          "type": "Boolean"
        }
      ]
    },

    // ── 2. Security-group scoped, both enabledSecurityGroups & excludedSecurityGroups ────────
    {
      "settingName": "AdminApisIncludeDetailedMetadata",
      "title": "Enhance admin APIs responses with detailed metadata",
      "enabled": true,
      "canSpecifySecurityGroups": true,
      "enabledSecurityGroups": [
        {
          "graphId": "11111111-1111-1111-1111-111111111111",
          "name": "Example-Security-Group-A"
        },
        {
          "graphId": "22222222-2222-2222-2222-222222222222",
          "name": "Example-Security-Group-B"
        }
      ],
      "excludedSecurityGroups": [
        {
          "graphId": "33333333-3333-3333-3333-333333333333",
          "name": "Example-Excluded-Group-C"
        }
      ],
      "tenantSettingGroup": "Admin API settings"
    },

    // ── 3. Non-empty properties array (Url type) ──────────────────────────────────────────────
    {
      "settingName": "TenantSettingPublishGetHelpInfo",
      "title": "Publish \"Get Help\" information",
      "enabled": true,
      "canSpecifySecurityGroups": true,
      "tenantSettingGroup": "Help and support settings",
      "properties": [
        { "name": "TrainingDocumentation", "value": "https://example.contoso.com/training", "type": "Url" },
        { "name": "DiscussionForum",        "value": "https://example.contoso.com/forum",   "type": "Url" },
        { "name": "LicensingRequests",      "value": "https://example.contoso.com/license", "type": "Url" },
        { "name": "HelpDesk",              "value": "https://example.contoso.com/helpdesk", "type": "Url" }
      ]
    },

    // ── 4. Delegated to capacity (delegateToCapacity: true) ───────────────────────────────────
    {
      "settingName": "EnableAOAI",
      "title": "Users can use Copilot and other features powered by Azure OpenAI",
      "enabled": true,
      "canSpecifySecurityGroups": true,
      "delegateToCapacity": true,
      "tenantSettingGroup": "Copilot and Azure OpenAI Service"
    },

    // ── 5. Delegated to workspace + domain, disabled ─────────────────────────────────────────
    {
      "settingName": "ExportToPowerPoint",
      "title": "Export reports as PowerPoint presentations or PDF documents",
      "enabled": false,
      "canSpecifySecurityGroups": true,
      "delegateToWorkspace": false,
      "delegateToDomain": false,
      "tenantSettingGroup": "Export and sharing settings"
    },

    // ── 6. Certification — Url property + domain delegation ──────────────────────────────────
    {
      "settingName": "CertifyDatasets",
      "title": "Certification",
      "enabled": true,
      "canSpecifySecurityGroups": true,
      "delegateToDomain": true,
      "enabledSecurityGroups": [
        {
          "graphId": "44444444-4444-4444-4444-444444444444",
          "name": "Example-Certifiers-Group"
        }
      ],
      "tenantSettingGroup": "Export and sharing settings",
      "properties": [
        {
          "name": "CertificationDocumentationUrl",
          "value": "https://example.contoso.com/certification-policy",
          "type": "Url"
        }
      ]
    },

    // ── 7. Integer property (workspace retention period) ──────────────────────────────────────
    {
      "settingName": "ConfigureFolderRetentionPeriod",
      "title": "Define workspace retention period",
      "enabled": true,
      "canSpecifySecurityGroups": false,
      "tenantSettingGroup": "Workspace settings",
      "properties": [
        {
          "name": "FolderRetentionPeriod",
          "value": "30",
          "type": "Integer"
        }
      ]
    }

  ],
  "continuationToken": null,
  "continuationUri": null
}
```

> Note: When there are no further pages, `continuationToken` and `continuationUri` are **absent**
> from the response object entirely (not present as `null`). The `null` values above are shown for
> documentation clarity only.

### Field-by-field schema reference — `TenantSetting` object

| Field | Type | Presence | Notes |
|---|---|---|---|
| `settingName` | `string` | **Always** | Internal programmatic key; used as the canonical identifier for comparison. |
| `title` | `string` | **Always** | Human-readable display name shown in the admin portal. |
| `enabled` | `boolean` | **Always** | `true` = feature enabled (for all org or for listed groups). `false` = disabled. |
| `canSpecifySecurityGroups` | `boolean` | **Always** | `false` = setting applies to entire org; no group scoping is possible. `true` = groups can be specified. |
| `tenantSettingGroup` | `string` | **Always** | Category string as shown in the admin portal (e.g. `"Export and sharing settings"`, `"Admin API settings"`). |
| `enabledSecurityGroups` | `TenantSettingSecurityGroup[]` | **Conditional** | Present only when `canSpecifySecurityGroups: true` AND specific groups have been configured. Absent (not `[]`) when the setting is enabled for the entire org. |
| `excludedSecurityGroups` | `TenantSettingSecurityGroup[]` | **Conditional** | Present only when specific groups are explicitly excluded. Absent (not `[]`) when none. |
| `properties` | `TenantSettingProperty[]` | **Conditional** | Present only for settings that carry supplementary configuration values (e.g. documentation URLs, numeric thresholds, Boolean sub-options). Absent when the setting has no sub-properties. |
| `delegateToCapacity` | `boolean` | **Optional** | When `true`, a capacity admin can override this setting at capacity level. Absent if the setting is not capacity-delegatable. |
| `delegateToDomain` | `boolean` | **Optional** | When `true`, a domain admin can override this setting. Absent if not domain-delegatable. |
| `delegateToWorkspace` | `boolean` | **Optional** | When `true`, a workspace admin can override this setting. Absent if not workspace-delegatable. |

### Nested type — `TenantSettingSecurityGroup`

| Field | Type | Presence | Notes |
|---|---|---|---|
| `graphId` | `string` (UUID) | **Always** | Microsoft Entra object ID of the security group. |
| `name` | `string` | **Always** | Display name of the group at the time the setting was saved. May lag behind Entra renames. |

### Nested type — `TenantSettingProperty`

| Field | Type | Presence | Notes |
|---|---|---|---|
| `name` | `string` | **Always** | Property key name (e.g. `"CreateP2w"`, `"CertificationDocumentationUrl"`). |
| `value` | `string` | **Always** | Always serialised as a string regardless of semantic type (e.g. `"true"`, `"30"`, a URL string). |
| `type` | `TenantSettingPropertyType` | **Always** | Enum; see below. |

### Enum — `TenantSettingPropertyType`

| Value | UI widget | Notes |
|---|---|---|
| `FreeText` | Any-string text box | ⚠️ Observed as `"Freetext"` (lowercase _t_) in some real-world responses (`NatVanG/fab-inspector:DocsExamples/Sample-TenantSettings.json:670`). Normalize case when comparing. |
| `Url` | URL-only text box | |
| `Boolean` | Checkbox | `value` will be `"true"` or `"false"` as a string. |
| `MailEnabledSecurityGroup` | Mail-enabled group picker | |
| `Integer` | Integer-only text box | `value` is a numeric string. |

> ⚠️ **Case conflict:** Official docs specify `FreeText`; at least one observed real-world response
> uses `Freetext`. Comparison code should normalize to lowercase before equality checks.

> Source for all schema types:
> [learn.microsoft.com — List Tenant Settings § Definitions](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings);
> real-world structure cross-referenced from
> `NatVanG/fab-inspector:DocsExamples/Sample-TenantSettings.json` (SHA: 6f511411748c) and
> `bidgeir/Mastering-Fabric-Administration:Extra/AdminSettings.json` (SHA: 241c4352779c).

---

## 3. Catalog of Well-Known Setting Names

All `settingName` values below are verified against live response samples
(`NatVanG/fab-inspector:DocsExamples/Sample-TenantSettings.json` and
`bidgeir/Mastering-Fabric-Administration:Extra/AdminSettings.json`), cross-referenced with the
[Microsoft Fabric tenant settings index](https://learn.microsoft.com/en-us/fabric/admin/tenant-settings-index).
Rows marked `(unverified)` do not appear in the captured samples and the name is inferred from
documentation text only.

**Exfil-risk weight (0–100):** Suggested relative sensitivity for data-exfiltration posture
comparison. Higher = greater exfil risk if enabled without controls. These are editorial
suggestions, not Microsoft designations.

### Export and sharing settings

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `PublishToWeb` | Publish to web | Export and sharing settings | **95** |
| `ExportToExcelSetting` | Export to Excel | Export and sharing settings | 70 |
| `ExportToCsv` | Export to .csv | Export and sharing settings | 70 |
| `ExportReport` | Download reports (.pbix) | Export and sharing settings | 65 |
| `ExportToPowerPoint` | Export reports as PowerPoint presentations or PDF documents | Export and sharing settings | 60 |
| `ExportToWord` | Export reports as Word documents | Export and sharing settings | 55 |
| `ExportToXML` | Export reports as XML documents | Export and sharing settings | 55 |
| `ExportToImage` | Export reports as image files | Export and sharing settings | 45 |
| `ExportToMHTML` | Export reports as MHTML documents | Export and sharing settings | 45 |
| `ExportVisualImageTenant` | Copy and paste visuals | Export and sharing settings | 40 |
| `Printing` | Print dashboards and reports | Export and sharing settings | 35 |
| `LiveConnection` | Users can work with semantic models in Excel using a live connection | Export and sharing settings | 55 |
| `AllowPowerBIASDQOnTenant` | Allow DirectQuery connections to Power BI semantic models | Export and sharing settings | 50 |
| `StorytellingTenant` | Enable Power BI add-in for PowerPoint | Export and sharing settings | 45 |

### External sharing settings

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `AllowExternalDataSharingSwitch` | External data sharing (OneLake shortcut links) | Export and sharing settings | **90** |
| `AllowExternalDataSharingReceiverSwitch` | Users can accept external data shares | Export and sharing settings | 75 |
| `ExternalSharingV2` | Users can invite guest users to collaborate through item sharing and permissions | Export and sharing settings | 70 |
| `AllowGuestUserToAccessSharedContent` | Guest users can access Microsoft Fabric | Export and sharing settings | 65 |
| `ElevatedGuestsTenant` | Guest users can browse and access Fabric content | Export and sharing settings | 60 |
| `AllowGuestLookup` | Users can see guest users in lists of suggested people | Export and sharing settings | 20 |
| `ShareLinkToEntireOrg` | Allow shareable links to grant access to everyone in your organization | Export and sharing settings | 55 |
| `EmailSubscriptionsToExternalUsers` | Users can send email subscriptions to external users | Export and sharing settings | 60 |
| `EmailSubscriptionsToB2BUsers` | B2B guest users can set up and be subscribed to email subscriptions | Export and sharing settings | 40 |
| `EmailSubscriptionTenant` | Users can set up email subscriptions | Export and sharing settings | 30 |
| `EnableDatasetInPlaceSharing` | Allow specific users to turn on external data sharing (dataset in-place) | Export and sharing settings | 70 |
| `ExternalDatasetSharingTenant` | Guest users can work with shared semantic models in their own tenants | Export and sharing settings | 65 |

### AI / Copilot and Azure OpenAI egress

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `EnableAOAI` | Users can use Copilot and other features powered by Azure OpenAI | Copilot and Azure OpenAI Service | **80** |
| `AllowSendAOAIDataToOtherRegions` | Data sent to Azure OpenAI can be processed outside your capacity's geographic region, compliance boundary, or national cloud instance | Copilot and Azure OpenAI Service | **85** |
| `AllowStoreAOAIDataInOtherRegions` | Data sent to Azure OpenAI can be stored outside your capacity's geographic region, compliance boundary, or national cloud instance | Copilot and Azure OpenAI Service | **85** |
| `ImmersiveTenantAdminSwitch` | Users can access a standalone, cross-item Power BI Copilot experience (preview) | Copilot and Azure OpenAI Service | 60 |
| `CopilotCapacitySetupPermissionSwitch` | Capacities can be designated as Fabric Copilot capacities | Copilot and Azure OpenAI Service | 30 |
| `AISkillArtifactTenantSwitch` | Users can create and share Data agent item types (preview) | Microsoft Fabric | 65 |

### Service principal / admin API access

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `AllowServicePrincipalsUseReadAdminAPIs` | Service principals can access read-only admin APIs | Admin API settings | **75** |
| `AllowServicePrincipalsUseWriteAdminAPIs` | Service principals can access admin APIs used for updates | Admin API settings | **80** |
| `AdminApisIncludeDetailedMetadata` | Enhance admin APIs responses with detailed metadata | Admin API settings | 55 |
| `AdminApisIncludeExpressions` | Enhance admin APIs responses with DAX and mashup expressions | Admin API settings | 65 |
| `ServicePrincipalAccessGlobalAPIs` | Service principals can create workspaces, connections, and deployment pipelines | Developer settings | 70 |
| `ServicePrincipalAccessPermissionAPIs` | Service principals can call Fabric public APIs | Developer settings | 70 |
| `AllowServicePrincipalsCreateAndUseProfiles` | Allow service principals to create and use profiles | Developer settings | 50 |
| `Embedding` | Embed content in apps | Developer settings | 45 |
| `BlockResourceKeyAuthentication` | Block ResourceKey Authentication | Developer settings | 25 |

### Custom visuals / external code

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `CustomVisualsTenant` | Allow visuals created using the Power BI SDK | Power BI visuals | 60 |
| `CertifiedCustomVisualsTenant` | Add and use certified visuals only (block uncertified) | Power BI visuals | 15 |
| `AllowCVToExportDataToFileTenant` | Allow downloads from custom visuals | Power BI visuals | 70 |
| `AllowCVAuthenticationTenant` | AppSource Custom Visuals SSO | Power BI visuals | 55 |
| `AllowCVLocalStorageV2Tenant` | Allow access to the browser's local storage | Power BI visuals | 30 |
| `RScriptVisual` | Interact with and share R and Python visuals | R and Python visuals settings | 50 |
| `WebContentTilesTenant` | Web content on dashboard tiles | Dashboard settings | 45 |

### OneLake / external data access

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `OneLakeForThirdParty` | Users can access data stored in OneLake with apps external to Fabric | OneLake settings | **80** |
| `OneLakeFileExplorer` | Users can sync data in OneLake with the OneLake File Explorer app | OneLake settings | 55 |
| `AllowGetOneLakeUDK` | Use short-lived user-delegated SAS tokens (preview) | OneLake settings | 50 |
| `AllowOneLakeUDK` | Authenticate with OneLake user-delegated SAS tokens (preview) | OneLake settings | 50 |
| `ASWritethruContinuousExportTenantSwitch` | Semantic models can export data to OneLake | Integration settings | 40 |
| `CDSAManagement` | Create and use Gen1 dataflows | Gen1 dataflow settings | 35 |

### Cross-workspace semantic model usage

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `UseDatasetsAcrossWorkspaces` | Use semantic models across workspaces | Workspace settings | 40 |
| `DatasetExecuteQueries` | Semantic Model Execute Queries REST API | Integration settings | 55 |
| `OnPremAnalyzeInExcel` | Allow XMLA endpoints and Analyze in Excel with on-premises semantic models | Integration settings | 50 |

### Developer / Git features

| `settingName` | Title | Category | Exfil-risk weight |
|---|---|---|---|
| `GitIntegrationTenantSwitch` | Users can synchronize workspace items with their Git repositories | Git integration | 50 |
| `GitIntegrationCrossGeoTenantSwitch` | Users can export items to Git repositories in other geographical locations | Git integration | 65 |
| `GitIntegrationSensitivityLabelsTenantSwitch` | Users can export workspace items with applied sensitivity labels to Git repositories | Git integration | 55 |
| `GitHubTenantSettings` | Users can sync workspace items with GitHub repositories | Git integration | 55 |
| `FabricGAWorkloads` | Users can create Fabric items | Microsoft Fabric | 20 |

---

## 4. Related Delegated-Override Endpoints

All three endpoints are under the `Tenants` operation group in the Fabric Admin REST API.
All are **Preview** status. All require **Fabric administrator** role and `Tenant.Read.All` or
`Tenant.ReadWrite.All` scope. All support **service principal** and **managed identity** auth.
Rate limit is identical: **25 requests per minute**, `429 + Retry-After` on breach. All support
pagination via `continuationToken` (max 10,000 records per page).

> ⚠️ Note on per-ID variants: The original scope document described per-ID paths
> (`/{capacityId}/`, `/{domainId}/`, `/{workspaceId}/`). Microsoft only publishes
> per-ID listing for **capacities**; the domain and workspace variants are **bulk-only**.
> Per-ID domain and workspace override lookup is not confirmed in the v1 API surface.

---

### 4.1 Capacity delegated overrides — all capacities

```
GET https://api.fabric.microsoft.com/v1/admin/capacities/delegatedTenantSettingOverrides
```

Returns all capacity-level overrides across the entire tenant.

**Response shape sketch:**

```json
{
  "value": [
    {
      "id": "<capacityId (string)>",
      "tenantSettings": [
        {
          "settingName": "string",
          "title": "string",
          "enabled": true,
          "canSpecifySecurityGroups": true,
          "enabledSecurityGroups": [ { "graphId": "...", "name": "..." } ],
          "excludedSecurityGroups": [],
          "properties": [],
          "tenantSettingGroup": "string",
          "delegateToWorkspace": false,
          "delegatedFrom": "Tenant | Capacity | Domain"
        }
      ]
    }
  ],
  "continuationToken": "MSwxMDAwMCww",
  "continuationUri": "https://api.fabric.microsoft.com/v1/admin/capacities/delegatedTenantSettingOverrides?continuationToken=..."
}
```

Key difference vs. tenant-level: the inner array is `tenantSettings` (not `value`), each setting
gains a `delegatedFrom` enum field (`Tenant | Capacity | Domain`), and the outer object
contains `id` = capacity GUID.

> Source: [learn.microsoft.com — List Capacities Tenant Settings Overrides](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-capacities-tenant-settings-overrides)

---

### 4.2 Capacity delegated overrides — single capacity

```
GET https://api.fabric.microsoft.com/v1/admin/capacities/{capacityId}/delegatedTenantSettingOverrides
```

Same response shape as 4.1 but scoped to one capacity. Also supports DELETE and UPDATE on a named
setting override (`/{capacityId}/delegatedTenantSettingOverrides/{tenantSettingName}`).

> Source: confirmed from Swagger spec
> (`microsoft/mcp:tools/Fabric.Mcp.Tools.Docs/src/Resources/fabric-rest-api-specs/contents/admin/swagger.json`)
> and PowerShell implementation `dataplat/FabricTools:src/Public/Tenant/Get-FabricCapacityTenantSettingOverrides.ps1`.
> Also documented at [learn.microsoft.com — List Capacity Tenant Settings Overrides By Capacity Id](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-capacity-tenant-settings-overrides-by-capacity-id).

---

### 4.3 Domain delegated overrides — all domains (bulk only)

```
GET https://api.fabric.microsoft.com/v1/admin/domains/delegatedTenantSettingOverrides
```

**Response shape sketch:**

```json
{
  "value": [
    {
      "id": "<domainId (UUID)>",
      "tenantSettings": [
        {
          "settingName": "string",
          "title": "string",
          "enabled": true,
          "canSpecifySecurityGroups": true,
          "enabledSecurityGroups": [],
          "excludedSecurityGroups": [],
          "tenantSettingGroup": "string",
          "delegateToWorkspace": false,
          "delegatedFrom": "Tenant | Capacity | Domain"
        }
      ]
    }
  ],
  "continuationToken": "...",
  "continuationUri": "..."
}
```

> ⚠️ No per-domain-ID listing endpoint is documented. A per-ID path
> (`/domains/{domainId}/delegatedTenantSettingOverrides`) is **not confirmed** in the v1 API
> surface as of this writing.

> Source: [learn.microsoft.com — List Domains Tenant Settings Overrides](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-domains-tenant-settings-overrides)

---

### 4.4 Workspace delegated overrides — all workspaces (bulk only)

```
GET https://api.fabric.microsoft.com/v1/admin/workspaces/delegatedTenantSettingOverrides
```

**Response shape sketch:**

```json
{
  "value": [
    {
      "id": "<workspaceId (UUID)>",
      "tenantSettings": [
        {
          "settingName": "string",
          "title": "string",
          "enabled": true,
          "canSpecifySecurityGroups": true,
          "enabledSecurityGroups": [],
          "excludedSecurityGroups": [],
          "tenantSettingGroup": "string",
          "delegatedFrom": "Tenant | Capacity | Domain"
        }
      ]
    }
  ],
  "continuationToken": "...",
  "continuationUri": "..."
}
```

Note: `WorkspaceTenantSetting` does **not** include a `delegateToWorkspace` field (it would be
self-referential); otherwise the schema mirrors the domain variant.

> ⚠️ No per-workspace-ID listing endpoint is documented. A per-ID path
> (`/workspaces/{workspaceId}/delegatedTenantSettingOverrides`) is **not confirmed** in the v1 API
> surface as of this writing.

> Source: [learn.microsoft.com — List Workspaces Tenant Settings Overrides](https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-workspaces-tenant-settings-overrides)

---

## 5. Auth Notes for Two-Tenant Scenarios

### 5.1 Primary token audience

The canonical token audience for all Fabric REST APIs (including the admin tenant settings
endpoint) is:

```
https://api.fabric.microsoft.com/.default
```

Scopes are expressed as full URIs:

```
https://api.fabric.microsoft.com/Tenant.Read.All
```

The Microsoft Fabric API quickstart demonstrates acquiring a token with this audience using MSAL:

```csharp
string[] scopes = new string[] {
    "https://api.fabric.microsoft.com/Tenant.Read.All"
};
```

> Source: [learn.microsoft.com — Fabric API Quickstart](https://learn.microsoft.com/en-us/rest/api/fabric/articles/get-started/fabric-api-quickstart)

---

### 5.2 Power BI legacy audience — back-compat status

The legacy Power BI REST API audience is:

```
https://analysis.windows.net/powerbi/api/.default
```

**Official Microsoft documentation does not explicitly state** that this audience is accepted
by the Fabric v1 admin API (`api.fabric.microsoft.com/v1/admin/tenantsettings`). The Power BI
audience is used for the classic Power BI REST endpoints at `api.powerbi.com`.

Community references (e.g., `fredgis/fabric-foundry-kb:markdown/Fabric_Admin_Guide.md:270`)
document both audiences side-by-side, implying they are **distinct resource IDs for separate
services**. A token issued to `analysis.windows.net/powerbi/api` may be accepted by the Fabric
service for some endpoints due to internal routing, but this should be treated as **unverified
behavior** rather than a documented guarantee.

**Recommendation for `fabric-tenant`:** Issue tokens to
`https://api.fabric.microsoft.com/.default` as the primary audience. If legacy Power BI
compatibility is needed (e.g., for the `api.powerbi.com/v1.0/myorg/admin/tenantSettings`
endpoint), issue a separate token with the Power BI audience. Do not assume cross-audience
substitution.

> ⚠️ **Conflicting community data:** Some open-source tooling targets both audiences and relies
> on the Fabric service's back-compat routing. If the helper detects a 401 when using the
> `api.fabric.microsoft.com` audience, attempting the Power BI audience as a fallback is a
> reasonable runtime workaround, but this behaviour is not contractually guaranteed.

---

### 5.3 Service principal access to admin endpoints

Using a service principal to call `/v1/admin/tenantsettings` requires **all four** of the
following conditions to be satisfied:

| # | Requirement | How to verify |
|---|---|---|
| 1 | Tenant setting **`AllowServicePrincipalsUseReadAdminAPIs`** is enabled AND the SP's Entra group is listed in `enabledSecurityGroups`. | Check the setting's own entry in the API response. |
| 2 | The SP must be a **member of the Entra security group** listed in condition 1. | Check Entra group membership. |
| 3 | The SP's app registration must **not** have any admin-consent–required Graph/Fabric permissions granted. | Azure portal > App registrations > Permissions. |
| 4 | The app must authenticate as a **confidential client** (client credentials flow) or use a **certificate**. No interactive / device-code prompt is available for service principals. | MSAL `ConfidentialClientApplication`. |

> Note: The `ServicePrincipalAccessPermissionAPIs` setting ("Service principals can call Fabric
> public APIs") governs access to the general Fabric item APIs. For **admin** APIs the relevant
> setting is `AllowServicePrincipalsUseReadAdminAPIs`. Both may need to be enabled depending on
> which endpoints the helper calls.

> Source: [learn.microsoft.com — Enable Service Principal Admin APIs](https://learn.microsoft.com/en-us/fabric/admin/enable-service-principal-admin-apis);
> [learn.microsoft.com — Identity Support](https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support)

---

### 5.4 Device-code flow

Device-code flow (MSAL `AcquireTokenWithDeviceCode`) is a **public client** interactive flow and
is **supported** for human-operated scenarios. It does not require a browser on the calling
machine, making it suitable for headless CLI tooling.

```python
# Python MSAL example (device-code flow)
import msal

app = msal.PublicClientApplication(
    client_id="<app-client-id>",
    authority="https://login.microsoftonline.com/<tenant-id>"
)
flow = app.initiate_device_flow(
    scopes=["https://api.fabric.microsoft.com/Tenant.Read.All"]
)
print(flow["message"])          # instruct user to visit aka.ms/devicelogin
result = app.acquire_token_by_device_flow(flow)
token = result["access_token"]
```

For the **two-tenant comparison use-case**, device-code is the recommended interactive flow:
run the device-code sequence twice (once per tenant) and store each token independently. Tokens
are bound to the specific Entra tenant used during the auth flow.

> Source: [learn.microsoft.com — Fabric API Quickstart](https://learn.microsoft.com/en-us/rest/api/fabric/articles/get-started/fabric-api-quickstart)
> (demonstrates interactive token acquisition; device-code is a public-client variant);
> MSAL device-code support is well-established across Microsoft identity platform.

---

## 6. Citations

All citations are inline throughout this document. Primary sources used:

| # | Resource | Type | URL |
|---|---|---|---|
| 1 | List Tenant Settings — API reference | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-tenant-settings |
| 2 | Admin Tenants — operation index | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants |
| 3 | List Capacities Tenant Settings Overrides | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-capacities-tenant-settings-overrides |
| 4 | List Domains Tenant Settings Overrides | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-domains-tenant-settings-overrides |
| 5 | List Workspaces Tenant Settings Overrides | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/admin/tenants/list-workspaces-tenant-settings-overrides |
| 6 | Tenant Settings Index | Official Microsoft Docs | https://learn.microsoft.com/en-us/fabric/admin/tenant-settings-index |
| 7 | About Tenant Settings | Official Microsoft Docs | https://learn.microsoft.com/en-us/fabric/admin/about-tenant-settings |
| 8 | Enable Service Principal Admin APIs | Official Microsoft Docs | https://learn.microsoft.com/en-us/fabric/admin/enable-service-principal-admin-apis |
| 9 | Identity Support | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/articles/identity-support |
| 10 | Fabric API Quickstart | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/articles/get-started/fabric-api-quickstart |
| 11 | Scopes reference | Official Microsoft Docs | https://learn.microsoft.com/en-us/rest/api/fabric/articles/scopes |
| 12 | Admin REST API Swagger spec | GitHub — microsoft/mcp | https://github.com/microsoft/mcp/blob/main/tools/Fabric.Mcp.Tools.Docs/src/Resources/fabric-rest-api-specs/contents/admin/swagger.json |
| 13 | Sample-TenantSettings.json (real-world response) | GitHub — NatVanG/fab-inspector | https://github.com/NatVanG/fab-inspector/blob/main/DocsExamples/Sample-TenantSettings.json |
| 14 | AdminSettings.json (real-world response) | GitHub — bidgeir/Mastering-Fabric-Administration | https://github.com/bidgeir/Mastering-Fabric-Administration/blob/main/Extra/AdminSettings.json |
| 15 | Get-FabricCapacityTenantSettingOverrides.ps1 | GitHub — dataplat/FabricTools | https://github.com/dataplat/FabricTools/blob/main/src/Public/Tenant/Get-FabricCapacityTenantSettingOverrides.ps1 |
| 16 | Fabric Admin Guide (audience table) | GitHub — fredgis/fabric-foundry-kb *(community)* | https://github.com/fredgis/fabric-foundry-kb/blob/main/markdown/Fabric_Admin_Guide.md |