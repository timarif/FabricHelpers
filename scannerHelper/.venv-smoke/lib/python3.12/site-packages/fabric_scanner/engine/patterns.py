"""Static detection data: URL schemes, regex PATTERNS, import categories.

Ported from `_v2_cells/04_scanner.py` lines 17-389 with no behavior changes.
Splitting these out of the runtime code makes the rule tables testable in
isolation and reviewable in a PR diff without scrolling past helpers.
"""
from __future__ import annotations

import re

# --- URL schemes ------------------------------------------------------------
URL_PROTOCOL_SCHEMES = [
    "http://", "https://", "ftp://", "ftps://", "sftp://",
    "abfs://", "abfss://", "wasb://", "wasbs://", "adl://",
    "s3://", "s3a://", "s3n://", "gs://",
    "hdfs://", "viewfs://", "dbfs://",
    "jdbc:", "odbc:", "mongodb://", "mongodb+srv://",
    "postgresql://", "postgres://", "mysql://", "mssql://",
    "redis://", "rediss://", "amqp://", "amqps://",
    "kafka://", "kinesis://", "eventhubs://",
    "mqtt://", "mqtts://",
    "ssh://", "scp://", "smb://", "nfs://", "tcp://", "udp://",
]

_scheme_prefixes: list[str] = []
for _s in URL_PROTOCOL_SCHEMES:
    _p = _s.rstrip(":/")
    if _p and _p not in _scheme_prefixes:
        _scheme_prefixes.append(re.escape(_p))
_schemes_alt = "|".join(sorted(_scheme_prefixes, key=len, reverse=True))

URL_RE = re.compile(
    r'(?P<url>(?:' + _schemes_alt + r')s?://[^\s"\'`<>)\]},;]+'
    r'|(?:' + _schemes_alt + r')s?:[^\s"\'`<>)\]},;]+'
    r'|\bwww\.[^\s"\'`<>)\]},;]+\.[^\s"\'`<>)\]},;]+)',
    re.IGNORECASE,
)
TRAILING_CHARS = '.,;:!?)]}>"\'`'

BENIGN_URL_PATTERNS = [
    re.compile(r'https?://(localhost|127\.0\.0\.1|0\.0\.0\.0)(:|/|$)', re.I),
    re.compile(r'https?://json\.schemastore\.org/', re.I),
    re.compile(r'https?://schemas?\.(microsoft|xmlsoap|w3)\.', re.I),
    re.compile(r'https?://(pypi|pip|conda|anaconda)\.(org|io)/', re.I),
    re.compile(r'https?://(docs|learn|aka)\.(microsoft|python|spark)\.', re.I),
    re.compile(r'https?://spark\.apache\.org/', re.I),
    re.compile(r'^file://', re.I),
]

READ_CONTEXT_RE = re.compile(
    r'(?:\brequests?\.(?:get|head|options)\s*\('
    r'|\bspark\.read\b'
    r'|\.read_\w+\s*\('
    r'|\bdownload\w*\s*\('
    r'|!\s*wget\b)',
    re.I,
)
WRITE_CONTEXT_RE = re.compile(
    r'(?:\brequests?\.(?:post|put|patch|delete)\s*\('
    r'|\.write\.\w+'
    r'|\.save\s*\('
    r'|\.to_\w+\s*\('
    r'|\bupload\w*\s*\('
    r'|\.write_\w+\s*\()',
    re.I,
)


# --- Suspicious imports -----------------------------------------------------
SUSPICIOUS_IMPORTS = {
    "requests", "httpx", "urllib", "urllib3", "http.client", "aiohttp", "pycurl",
    "boto3", "botocore", "azure.storage.blob", "azure.storage.filedatalake",
    "google.cloud.storage", "gcsfs", "s3fs", "adlfs",
    "paramiko", "ftplib", "pysftp", "smtplib",
    "socket", "websocket", "websockets",
    "grpc", "grpcio",
    "pymongo", "kafka", "confluent_kafka", "pika",
    "azure.eventhub", "azure.servicebus",
    "telegram", "slack_sdk", "discord", "twilio", "sendgrid",
    "msgraph", "O365", "office365",
    "ctypes", "cffi",
    "dropbox", "boxsdk", "pydrive", "pydrive2", "googleapiclient",
    "mega", "firebase_admin", "pyrebase", "supabase", "cloudinary", "b2sdk",
    "pyperclip", "clipboard",
}

IMPORT_CATEGORIES = {
    "requests": "http_exfiltration", "httpx": "http_exfiltration",
    "urllib": "http_exfiltration", "aiohttp": "http_exfiltration",
    "boto3": "cloud_storage_write", "botocore": "cloud_storage_write",
    "azure.storage.blob": "cloud_storage_write",
    "google.cloud.storage": "cloud_storage_write",
    "paramiko": "filesystem_exfiltration", "ftplib": "filesystem_exfiltration",
    "smtplib": "email_exfiltration",
    "socket": "raw_socket_network", "websocket": "raw_socket_network",
    "pymongo": "external_database_write", "kafka": "external_database_write",
    "telegram": "webhook_exfiltration", "slack_sdk": "webhook_exfiltration",
    "discord": "webhook_exfiltration",
    "msgraph": "api_exfiltration", "O365": "api_exfiltration",
    "dropbox": "cloud_storage_write", "boxsdk": "cloud_storage_write",
    "pydrive2": "cloud_storage_write", "googleapiclient": "cloud_storage_write",
    "mega": "cloud_storage_write", "firebase_admin": "cloud_storage_write",
    "supabase": "cloud_storage_write", "cloudinary": "cloud_storage_write",
    "ctypes": "native_code_execution", "cffi": "native_code_execution",
}


# --- 104 regex patterns: union of NotebookAudit + secret extensions ---------
# Tuple format: (compiled_regex, category, severity, message)
PATTERNS: list[tuple[re.Pattern, str, str, str]] = [
    # --- HTTP exfiltration ---
    (re.compile(r'(requests|httpx|urllib)\s*\.\s*(post|put|patch)\s*\(', re.I),
     "http_exfiltration", "high", "HTTP POST/PUT/PATCH request detected"),
    (re.compile(r'https?://[^\s\'"]+\.(ngrok|burpcollaborator|requestbin|pipedream|webhook\.site|hookbin|canarytokens|interactsh)', re.I),
     "http_exfiltration", "critical", "Known exfiltration service URL"),
    (re.compile(r'https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}[:/]', re.I),
     "http_exfiltration", "high", "HTTP request to raw IP address"),
    (re.compile(r'urllib\.request\.urlopen\s*\([^,)]+,\s*(data|b["\'])', re.I),
     "http_exfiltration", "high", "urllib.request.urlopen() with data — POST equivalent"),
    (re.compile(r'urllib\.request\.urlretrieve\s*\(|urlretrieve\s*\(', re.I),
     "http_exfiltration", "medium", "urlretrieve() downloads file to local disk"),

    # --- Cloud storage / file sharing services ---
    (re.compile(r'(api\.dropboxapi\.com|content\.dropboxapi\.com|dropbox\.com/oauth2)', re.I),
     "cloud_storage_write", "high", "Dropbox API endpoint"),
    (re.compile(r'\b(dropbox\.Dropbox|DropboxOAuth2FlowNoRedirect)\s*\(', re.I),
     "cloud_storage_write", "high", "Dropbox SDK client initialization"),
    (re.compile(r'(api\.box\.com|upload\.box\.com|box\.com/api)', re.I),
     "cloud_storage_write", "high", "Box.com API endpoint"),
    (re.compile(r'(drive\.google\.com|www\.googleapis\.com/upload/drive|www\.googleapis\.com/drive)', re.I),
     "cloud_storage_write", "high", "Google Drive API endpoint"),
    (re.compile(r'(mega\.nz|mega\.co\.nz|g\.api\.mega\.co\.nz)', re.I),
     "cloud_storage_write", "high", "MEGA cloud storage endpoint"),
    (re.compile(r'(wetransfer\.com/api|we\.tl)', re.I),
     "cloud_storage_write", "high", "WeTransfer API/URL"),
    (re.compile(r'(api\.pcloud\.com|pcloud\.com/oauth2)', re.I),
     "cloud_storage_write", "high", "pCloud API endpoint"),
    (re.compile(r'(firebaseio\.com|firebasestorage\.googleapis\.com)', re.I),
     "cloud_storage_write", "high", "Firebase endpoint"),
    (re.compile(r'\b\w+\.supabase\.co\b', re.I),
     "cloud_storage_write", "high", "Supabase endpoint"),
    (re.compile(r'(api\.cloudinary\.com|cloudinary\.uploader)', re.I),
     "cloud_storage_write", "high", "Cloudinary upload endpoint"),
    (re.compile(r'(backblazeb2\.com|b2_authorize_account|b2_upload_file)', re.I),
     "cloud_storage_write", "high", "Backblaze B2 storage endpoint"),
    (re.compile(r'(icloud\.com/api|setup\.icloud\.com)', re.I),
     "cloud_storage_write", "high", "iCloud API endpoint"),
    (re.compile(r'\b(upload_blob|upload_file|upload_fileobj|upload_from_string|upload_data|put_object|put_block_blob|put_item|put_record)\s*\(', re.I),
     "cloud_storage_write", "high", "Cloud storage upload SDK call"),

    # --- Paste / gist services ---
    (re.compile(r'(pastebin\.com/api|api\.paste\.ee|dpaste\.com/api|ix\.io|sprunge\.us|hastebin\.com)', re.I),
     "api_exfiltration", "high", "Paste service API — data exfiltration risk"),
    (re.compile(r'api\.github\.com/gists', re.I),
     "api_exfiltration", "high", "GitHub Gists API — data exfiltration risk"),
    (re.compile(r'(gitlab\.com/api.*snippets|snippets\.gitlab\.com)', re.I),
     "api_exfiltration", "high", "GitLab Snippets API"),
    (re.compile(r'api\.airtable\.com', re.I),
     "api_exfiltration", "high", "Airtable API endpoint"),
    (re.compile(r'api\.notion\.(com|so)', re.I),
     "api_exfiltration", "high", "Notion API endpoint"),

    # --- Webhooks ---
    (re.compile(r'https://hooks\.slack\.com/services/', re.I),
     "webhook_exfiltration", "critical", "Slack incoming webhook URL"),
    (re.compile(r'https://discord(app)?\.com/(api/)?webhooks/', re.I),
     "webhook_exfiltration", "critical", "Discord webhook URL"),
    (re.compile(r'https://api\.telegram\.org/bot', re.I),
     "webhook_exfiltration", "critical", "Telegram bot API"),
    (re.compile(r'https://[^\s]*\.execute-api\.[^\s]*\.amazonaws\.com', re.I),
     "webhook_exfiltration", "high", "AWS API Gateway endpoint"),
    (re.compile(r'https://[^\s]+(\.workers\.dev|\.vercel\.app|\.netlify\.app|\.pages\.dev|\.azurewebsites\.net)', re.I),
     "webhook_exfiltration", "high", "Serverless platform endpoint"),

    # --- Microsoft API abuse ---
    (re.compile(r'https://graph\.microsoft\.com/v\d+\.\d+/(me|users|groups|drives|sites)', re.I),
     "api_exfiltration", "high", "Microsoft Graph API call"),
    (re.compile(r'https://management\.azure\.com/subscriptions', re.I),
     "api_exfiltration", "high", "Azure Management API call"),
    (re.compile(r'https://api\.fabric\.microsoft\.com/v1/', re.I),
     "cross_workspace_operation", "high", "Fabric REST API call from within notebook"),
    (re.compile(r'https://api\.powerbi\.com/v1\.0/myorg/datasets/[^/]+/rows', re.I),
     "api_exfiltration", "critical", "Power BI streaming/push dataset API"),
    (re.compile(r'(GraphServiceClient|MSGraph|O365\.Account)\s*\(', re.I),
     "api_exfiltration", "critical", "Microsoft Graph SDK client"),

    # --- Credential access ---
    (re.compile(r'(mssparkutils|notebookutils)\.credentials\.(getSecret|getToken|getConnectionString|getFullConnectionString)', re.I),
     "credential_access", "high", "Fabric credential access"),
    (re.compile(r'(TokenLibrary|dbutils\.secrets)\.(get|getSecret|getToken)', re.I),
     "credential_access", "high", "Token/secret library access"),
    (re.compile(r'AccountKey\s*=\s*[A-Za-z0-9+/=]{40,}', re.I),
     "credential_access", "critical", "Hardcoded Storage Account Key"),
    (re.compile(r'(\?|&)sig=[A-Za-z0-9%+/=]{20,}', re.I),
     "credential_access", "critical", "SAS token with signature"),
    (re.compile(r'["\']https?://[^"\s]+\.blob\.core\.windows\.net[^"\s]*sig=[^"\s]+["\']', re.I),
     "credential_access", "critical", "SAS-tokened blob URL assignment"),
    (re.compile(r'(Password|pwd)\s*=\s*[^;\s"]{4,}', re.I),
     "credential_access", "high", "Hardcoded SQL password"),
    (re.compile(r'(client[_-]?secret|app[_-]?secret)\s*[=:]\s*["\']?[A-Za-z0-9~._-]{16,}', re.I),
     "credential_access", "critical", "Hardcoded client/app secret"),
    (re.compile(r'["\']Bearer\s+eyJ[A-Za-z0-9_-]{20,}', re.I),
     "credential_access", "critical", "Hardcoded Bearer JWT token"),
    (re.compile(r'SharedAccessKey\s*=\s*[A-Za-z0-9+/=]{30,}', re.I),
     "credential_access", "critical", "Hardcoded Event Hub / Service Bus key"),
    (re.compile(r'(openai[_-]?api[_-]?key|OPENAI_API_KEY)\s*[=:]\s*["\']?sk-[A-Za-z0-9]{20,}', re.I),
     "credential_access", "critical", "Hardcoded OpenAI API key"),
    (re.compile(r'(azure[_-]?openai[_-]?key|AZURE_OPENAI_KEY)\s*[=:]\s*["\']?[A-Fa-f0-9]{32}', re.I),
     "credential_access", "critical", "Hardcoded Azure OpenAI key"),
    (re.compile(r'(AccountKey|cosmosdb[_-]?key)\s*[=:]\s*["\']?[A-Za-z0-9+/=]{40,}', re.I),
     "credential_access", "critical", "Hardcoded Cosmos DB / Storage key"),
    (re.compile(r'(api[_-]?key|apikey|subscription[_-]?key|Ocp-Apim-Subscription-Key)\s*[=:]\s*["\']?[A-Za-z0-9]{16,}', re.I),
     "credential_access", "high", "Hardcoded API key"),
    (re.compile(r'(connection[_-]?string|conn[_-]?str)\s*[=:]\s*["\'][^"]{20,}["\']', re.I),
     "credential_access", "high", "Hardcoded connection string"),
    (re.compile(r'(secret|password|passwd|token|credential)\s*[=:]\s*["\'][^"\s]{8,}["\']', re.I),
     "credential_access", "medium", "Generic secret assignment"),
    (re.compile(r'spark\.conf\.set\s*\([^)]*account\.key[^)]*\)', re.I),
     "credential_access", "high", "Spark config with storage account key"),
    (re.compile(r'spark\.conf\.set\s*\(\s*["\'].*(account\.key|access\.key|secret|password|token)', re.I),
     "credential_access", "high", "Spark config with external credentials"),
    (re.compile(r'jdbc:[a-z]+://[^\s]*password=[^;\s"]{4,}', re.I),
     "credential_access", "critical", "JDBC URL with embedded password"),

    # --- API keys (provider-specific high-confidence formats) -------------
    (re.compile(r'\bAKIA[0-9A-Z]{16}\b'),
     "api_key_leak", "critical", "AWS Access Key ID (AKIA…)"),
    (re.compile(r'\bASIA[0-9A-Z]{16}\b'),
     "api_key_leak", "high", "AWS temporary session key (ASIA…)"),
    (re.compile(r'(?i)aws(.{0,20})?(secret|access)?[_-]?key[^\n]{0,20}["\'][A-Za-z0-9/+=]{40}["\']'),
     "api_key_leak", "critical", "AWS Secret Access Key (40-char base64)"),
    (re.compile(r'\bAIza[0-9A-Za-z_\-]{35}\b'),
     "api_key_leak", "critical", "Google API key (AIza…)"),
    (re.compile(r'\bya29\.[0-9A-Za-z_\-]{20,}'),
     "api_key_leak", "critical", "Google OAuth access token (ya29.…)"),
    (re.compile(r'\b[0-9]+-[0-9A-Za-z_]{32}\.apps\.googleusercontent\.com\b'),
     "api_key_leak", "high", "Google OAuth client ID"),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9]{36}\b'),
     "api_key_leak", "critical", "GitHub personal access token (ghp_/gho_/ghu_/ghs_/ghr_)"),
    (re.compile(r'\bgithub_pat_[A-Za-z0-9_]{82}\b'),
     "api_key_leak", "critical", "GitHub fine-grained PAT (github_pat_…)"),
    (re.compile(r'\bglpat-[A-Za-z0-9\-_]{20,}\b'),
     "api_key_leak", "critical", "GitLab personal access token (glpat-…)"),
    (re.compile(r'\bsk-ant-(?:api03|sid01|admin01)-[A-Za-z0-9_\-]{80,}\b'),
     "api_key_leak", "critical", "Anthropic API key (sk-ant-…)"),
    (re.compile(r'\bsk-(?:proj-)?[A-Za-z0-9]{20,}T3BlbkFJ[A-Za-z0-9]{20,}\b'),
     "api_key_leak", "critical", "OpenAI API key (sk-…T3BlbkFJ…)"),
    (re.compile(r'\bhf_[A-Za-z0-9]{30,}\b'),
     "api_key_leak", "critical", "Hugging Face token (hf_…)"),
    (re.compile(r'\bsk_(?:live|test)_[0-9a-zA-Z]{24,}\b'),
     "api_key_leak", "critical", "Stripe secret key (sk_live_ / sk_test_)"),
    (re.compile(r'\brk_(?:live|test)_[0-9a-zA-Z]{24,}\b'),
     "api_key_leak", "critical", "Stripe restricted key (rk_live_ / rk_test_)"),
    (re.compile(r'\bpk_(?:live|test)_[0-9a-zA-Z]{24,}\b'),
     "api_key_leak", "medium", "Stripe publishable key (pk_live_ / pk_test_)"),
    (re.compile(r'\bSG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{30,}\b'),
     "api_key_leak", "critical", "SendGrid API key (SG.…)"),
    (re.compile(r'\bkey-[a-f0-9]{32}\b'),
     "api_key_leak", "high", "Mailgun API key (key-…)"),
    (re.compile(r'\bxox[abprs]-[A-Za-z0-9-]{10,}\b'),
     "api_key_leak", "critical", "Slack token (xoxb-/xoxp-/xoxa-/xoxr-/xoxs-)"),
    (re.compile(r'\bSK[a-f0-9]{32}\b'),
     "api_key_leak", "critical", "Twilio API SID (SK…)"),
    (re.compile(r'\bAC[a-f0-9]{32}\b'),
     "api_key_leak", "high", "Twilio Account SID (AC…)"),
    (re.compile(r'\bsq0(?:atp|csp|idp)-[A-Za-z0-9_\-]{22,}\b'),
     "api_key_leak", "critical", "Square access/app token (sq0atp/csp/idp-…)"),
    (re.compile(r'\bnpm_[A-Za-z0-9]{36}\b'),
     "api_key_leak", "critical", "npm publish token (npm_…)"),
    (re.compile(r'\bpypi-AgEIcHlwaS5vcmcC[A-Za-z0-9_\-]{50,}\b'),
     "api_key_leak", "critical", "PyPI upload token (pypi-…)"),
    (re.compile(r'\bdop_v1_[a-f0-9]{64}\b'),
     "api_key_leak", "critical", "DigitalOcean personal access token (dop_v1_…)"),
    (re.compile(r'\bshpat_[a-f0-9]{32}\b'),
     "api_key_leak", "critical", "Shopify access token (shpat_…)"),
    (re.compile(r'\bshpss_[a-f0-9]{32}\b'),
     "api_key_leak", "critical", "Shopify shared secret (shpss_…)"),
    (re.compile(r'\b[MN][A-Za-z\d]{23,28}\.[\w-]{6,7}\.[\w-]{27,}\b'),
     "api_key_leak", "critical", "Discord bot token"),
    (re.compile(r'\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}'),
     "api_key_leak", "high", "Bare JWT token (eyJ…header.payload.signature)"),
    (re.compile(r'(?i)\b(secret|client[_-]?id|token|api[_-]?key)\b[^\n]{0,12}=\s*["\'][A-Za-z0-9_\-]{32,128}["\']\s*(?:#.*high[_\- ]entropy|$|\n)', re.MULTILINE),
     "api_key_leak", "medium", "High-entropy literal assigned to credential-shaped name"),

    # --- Shell / package install ---
    (re.compile(r'^!pip\s+install\b|^%pip\s+install\b|^%conda\s+install\b', re.I | re.MULTILINE),
     "in_notebook_package_install", "high", "In-notebook package installation"),
    (re.compile(r'pip\s+install\s+.*--(index-url|extra-index-url)\s+http', re.I),
     "in_notebook_package_install", "critical", "pip install from non-PyPI index"),
    (re.compile(r'^!(curl|wget|nc|ncat|netcat|scp|rsync|ssh|sftp|ftp)\b', re.I | re.MULTILINE),
     "shell_execution", "critical", "Shell command for network file transfer"),
    (re.compile(r'(os\.system|os\.popen|subprocess\.(run|Popen|call|check_output))\s*\(', re.I),
     "shell_execution", "high", "Shell command execution"),

    # --- Spark external writes ---
    (re.compile(r'\.format\s*\(\s*["\'](?:com\.mongodb|org\.apache\.spark\.sql\.cassandra|kafka|es\.spark)', re.I),
     "spark_external_write", "high", "Spark write with external connector format"),
    (re.compile(r'writeStream.*\.format\s*\(\s*["\'](?:kafka|eventhubs|socket|mqtt|kinesis)["\']\s*\)', re.I),
     "spark_streaming_exfiltration", "critical", "Spark streaming to external broker"),
    (re.compile(r'writeStream.*foreachBatch', re.I),
     "spark_streaming_exfiltration", "high", "Spark streaming foreachBatch — custom sink"),
    (re.compile(r'(dbutils\.fs\.cp|mssparkutils\.fs\.cp|shutil\.copy).*(?:s3|wasb|gs|abfss|adl|ftp)', re.I),
     "filesystem_exfiltration", "critical", "File copy to external cloud storage"),
    (re.compile(r'(dbutils\.fs\.mount|mssparkutils\.fs\.mount)', re.I),
     "spark_external_write", "high", "Mounting external storage"),
    (re.compile(r'(mssparkutils|notebookutils)\.fs\.(put|append|mv)\s*\(', re.I),
     "filesystem_exfiltration", "high", "mssparkutils/notebookutils file write/move"),

    # --- JDBC / database ---
    (re.compile(r'jdbc:(mysql|postgresql|sqlserver|oracle|db2|redshift|snowflake|bigquery)://[^\s\'"]+', re.I),
     "external_database_write", "high", "JDBC connection string to external database"),
    (re.compile(r'Server\s*=\s*[^;]+\.database\.windows\.net', re.I),
     "external_database_write", "high", "Azure SQL connection string"),

    # --- Email ---
    (re.compile(r'(smtplib\.SMTP|MIMEMultipart|MIMEText|send_message|sendmail)\s*[(\.]', re.I),
     "email_exfiltration", "high", "Email sending capability"),
    (re.compile(r'(api\.sendgrid\.com|api\.mailgun\.net|mandrillapp\.com/api|api\.sparkpost\.com)', re.I),
     "email_exfiltration", "high", "Transactional email API endpoint"),

    # --- DNS exfiltration ---
    (re.compile(r'(dns\.resolver|dnspython|socket\.getaddrinfo)', re.I),
     "dns_exfiltration", "high", "DNS resolution — potential DNS exfiltration"),

    # --- Encoding / obfuscation ---
    (re.compile(r'(exec|eval)\s*\(\s*(base64|codecs|bytes\.fromhex|bytearray)', re.I),
     "dynamic_code_execution", "critical", "Execution of decoded/deobfuscated code"),
    (re.compile(r'getattr\s*\(\s*__builtins__', re.I),
     "dynamic_code_execution", "critical", "Dynamic access to builtins — obfuscation"),

    # --- Polars / Pandas writes ---
    (re.compile(r'\.write_(?:delta|parquet|csv|json|ndjson|ipc|arrow|avro|excel|database)\s*\(', re.I),
     "filesystem_exfiltration", "medium", "Polars DataFrame write to file/database"),
    (re.compile(r'\.to_(?:csv|json|parquet|sql|excel|html|hdf|pickle|orc|feather|stata|gbq|xml)\s*\(', re.I),
     "filesystem_exfiltration", "medium", "Pandas DataFrame export to file/database"),

    # --- SQL DML ---
    (re.compile(r'\.execute\s*\(\s*[f"\']*(INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|MERGE\s+INTO)', re.I),
     "external_database_write", "medium", "SQL DML via .execute()"),
    (re.compile(r'spark\.sql\s*\(\s*f?["\']*(INSERT\s+INTO|UPDATE\s+|DELETE\s+FROM|MERGE\s+INTO)', re.I),
     "spark_external_write", "medium", "spark.sql() with data-modifying statement"),

    # --- Fabric APIs that need migration / update review ---
    (re.compile(r'\b(?:mssparkutils|notebookutils)\.fs\.fastcp\s*\(', re.I),
     "needs_update", "medium",
     "fastcp() bulk copy detected - flag for migration / review"),
    (re.compile(r'(?<!\.)\bfastcp\s*\(', re.I),
     "needs_update", "medium",
     "fastcp() bulk copy detected (bare call) - flag for migration / review"),
    (re.compile(r'from\s+(?:mssparkutils|notebookutils)\.fs\s+import\s+[^\n#]*\bfastcp\b', re.I),
     "needs_update", "medium",
     "fastcp imported - flag for migration / review"),
]


# --- Potential-write: destination-agnostic write API detection. -------------
WRITE_CALL_RE = re.compile(
    r"\.write_(?:delta|parquet|csv|json|ndjson|ipc|arrow|avro|excel|database)\s*\("
    r"|\.to_(?:csv|json|parquet|sql|excel|html|hdf|pickle|orc|feather|stata|gbq|xml)\s*\("
    r"|\.write\.(?:format|mode|option|partitionBy|saveAsTable|save|insertInto|jdbc)\s*\("
    r"|\.writeStream\.(?:format|trigger|option|outputMode|start|toTable|foreachBatch)\s*\("
    r"|\brequests?\.(?:post|put|patch|delete)\s*\("
    r"|\bhttpx?\.(?:post|put|patch|delete)\s*\("
    r"|\b(?:upload_blob|upload_file|upload_fileobj|upload_from_string|"
    r"upload_data|put_object|put_block_blob|put_item|put_record)\s*\("
    r"|\bmssparkutils\.fs\.(?:put|append|mv|cp|fastcp)\s*\("
    r"|\bnotebookutils\.fs\.(?:put|append|mv|cp|fastcp)\s*\("
    r"|\bdbutils\.fs\.(?:put|cp|mv)\s*\("
    r"|\.execute\s*\(\s*[fbur]*['\"]?(?:INSERT|UPDATE|DELETE|MERGE)\s"
    r"|\bspark\.sql\s*\(\s*f?['\"]?(?:INSERT|UPDATE|DELETE|MERGE)\s"
    r"|\bopen\s*\([^,)]*,\s*['\"][wax]b?",
    re.I,
)
