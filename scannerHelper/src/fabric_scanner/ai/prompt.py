"""AI Auditor prompt + response schema.

`AI_AUDIT_PROMPT` and `AI_AUDIT_RESPONSE_FORMAT` are taken verbatim from
the original NotebookAudit `fabric_notebook_ai_auditor.ipynb` so that
results stay comparable across the two implementations. Any change here
MUST bump `PROMPT_VERSION` — downstream tables stamp the prompt version
on every row so consumers can detect score drift.

The response is constrained by a JSON Schema enforced by Fabric AI
functions (`response_format`), so the parser can safely assume top-level
keys exist when `ai_error` is null. We still parse defensively in
`ai.runner` since malformed responses do occasionally slip through.
"""
from __future__ import annotations

# Bump this whenever AI_AUDIT_PROMPT or AI_AUDIT_RESPONSE_FORMAT changes
# in any way that could shift scoring behavior. Year-month-day-N format.
PROMPT_VERSION = "2026-05-22-1"


AI_AUDIT_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "fabric_notebook_exfiltration_audit",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "external_resource_access_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "0=no external access, 100=confirmed external access",
                },
                "exfiltration_risk_score": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "description": "0=no exfiltration risk, 100=clear high-risk data movement",
                },
                "sources": {
                    "type": "array",
                    "description": "External or workspace data sources read by the notebook chunk",
                    "items": {
                        "type": "object",
                        "properties": {
                            "endpoint": {
                                "type": "string",
                                "description": "Static endpoint or pseudocode for dynamic endpoint construction",
                            },
                            "type": {
                                "type": "string",
                                "description": "Protocol or service type such as https, abfss, s3, jdbc, smtp, webhook",
                            },
                            "deterministic": {
                                "type": "boolean",
                                "description": "True only when the full endpoint is a literal value in the notebook chunk",
                            },
                        },
                        "required": ["endpoint", "type", "deterministic"],
                        "additionalProperties": False,
                    },
                },
                "destinations": {
                    "type": "array",
                    "description": "External or workspace destinations written to by the notebook chunk",
                    "items": {
                        "type": "object",
                        "properties": {
                            "endpoint": {
                                "type": "string",
                                "description": "Static endpoint or pseudocode for dynamic endpoint construction",
                            },
                            "type": {
                                "type": "string",
                                "description": "Protocol or service type such as https, abfss, s3, jdbc, smtp, webhook",
                            },
                            "deterministic": {
                                "type": "boolean",
                                "description": "True only when the full endpoint is a literal value in the notebook chunk",
                            },
                        },
                        "required": ["endpoint", "type", "deterministic"],
                        "additionalProperties": False,
                    },
                },
                "rationale": {
                    "type": "string",
                    "description": "Brief justification for the scores and most important evidence in this chunk",
                },
            },
            "required": [
                "external_resource_access_score",
                "exfiltration_risk_score",
                "sources",
                "destinations",
                "rationale",
            ],
            "additionalProperties": False,
        },
    },
}


AI_AUDIT_PROMPT = """You are a cybersecurity reviewer for Microsoft Fabric Spark notebooks. Analyze this notebook chunk and return structured JSON that estimates external resource access and data exfiltration risk for the chunk. Later processing will combine all chunk results for the notebook.

Primary goal: identify whether this chunk can read from or write to resources outside the current Fabric workspace, including other Fabric workspaces, other tenants, public internet services, external cloud storage, databases, APIs, messaging systems, email, or file transfer endpoints.

Score external_resource_access_score from 0 to 100:
- 0: only relative/default Lakehouse, Spark table, or current-workspace operations; no external indicators.
- 1-20: capability only, such as imports of network/cloud/database libraries or endpoint variables with no use.
- 21-45: possible external access, such as dynamic endpoints, connection strings, SDK clients, or configurable paths.
- 46-70: clear external access, such as literal URLs, cloud URIs, JDBC/ODBC targets, REST calls, cross-workspace/cross-tenant Fabric or Power BI APIs.
- 71-100: multiple external targets, high-confidence non-workspace targets, or known exfiltration-capable services.

Score exfiltration_risk_score from 0 to 100:
- 0: no external access and no suspicious capability.
- 1-20: benign-looking read-only access or unused capability.
- 21-45: unclear intent, dynamic endpoint construction, credentials involved, or possible external writes.
- 46-70: data read from internal/workspace sources and written/sent externally; broad credentials; obfuscated or hidden endpoints.
- 71-100: likely malicious or unauthorized movement, such as webhook POSTs, personal storage, paste sites, email/messaging APIs, encoded/compressed payloads sent externally, credential harvesting, or staged exfiltration.

Look for these signals:
- Protocols and endpoints: http, https, ftp, sftp, ssh, scp, smb, nfs, abfs, abfss, wasb, s3, gs, jdbc, odbc, mongodb, redis, kafka, eventhubs, smtp.
- External services: blob/dfs storage accounts, S3/GCS, Azure SQL/Snowflake/Redshift/Postgres/MySQL, Graph/Fabric/Power BI REST APIs, webhooks, Slack/Teams/Discord/Telegram, SendGrid/Mailgun, Dropbox/Box/Google Drive/OneDrive/SharePoint, GitHub gists, paste sites, serverless URLs.
- Code patterns: requests/httpx/urllib/aiohttp, boto3, google.cloud, azure.storage, paramiko, smtplib, socket, Spark read/write/load/save, writeStream, pandas/polars exports, notebookutils or mssparkutils credentials/secrets, TokenLibrary, os.environ, spark.conf credentials.
- Risk amplifiers: internal read followed by external write, POST/PUT/PATCH/upload/send/copy/mount, dynamic URL/path construction, secrets/tokens/connection strings, base64/gzip/pickle/encryption before network/file write, eval/exec/import indirection, shell commands such as curl/wget/scp/nc.

Decision rules:
- Treat Fabric, Power BI, Graph, Azure, and Microsoft URLs as potentially external unless the code proves they target the current workspace/tenant.
- Workspace-relative paths like Files/..., Tables/..., default saveAsTable, or spark.table without external location are not external by themselves.
- Literal external destinations should raise both scores. Literal external read-only sources may raise access more than risk.
- Dynamic endpoints should be represented as pseudocode and scored by capability; dynamic destinations are riskier than dynamic sources.
- If this chunk contains only one side of a suspicious flow, score that partial capability and explain the missing context.
- Do not infer benign ownership from domain names alone. Prefer a human-review flag when intent is unclear, but keep access score evidence-based.

For sources and destinations:
- Include deterministically known endpoints as literal strings.
- For dynamic endpoints, include pseudocode using angle placeholders, for example storage_account + '.dfs.core.windows.net/' + container + '/' + path or BASE_URL + '/api/v1/upload?token=' + TOKEN.
- Put read endpoints in sources and write/send/upload/copy/export endpoints in destinations. If direction is unclear, include the endpoint in both arrays and explain uncertainty in rationale.
- Return empty arrays when no endpoints are found.

Return only JSON matching the required schema. No markdown, no extra text.

Notebook file: {file_name}
Chunk: {chunk_number} of {chunk_count}
Notebook code chunk:
{chunk_text}
"""
