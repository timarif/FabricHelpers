"""
HTTP-triggered Azure Function endpoints the NotebookChain sample notebooks call.

Programming model: Python v2 (decorator-based, single file).
Auth level:        function (callers send 'x-functions-key' header).

Endpoints:
    POST/GET  /api/HelloWorld         echoes the payload + stats
    POST/GET  /api/GetRepoInfo        calls GitHub API, returns curated repo info
    GET       /api/health             anonymous liveness probe
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
import requests

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# A per-instance id so load-test callers can see how many function instances
# Azure spun up to handle their traffic. Created once per cold start.
_INSTANCE_ID = uuid.uuid4().hex[:8]

# Optional GitHub PAT. Set as a function app setting (NOT in code).
#   az functionapp config appsettings set -n $APP -g $RG \
#       --settings "GITHUB_TOKEN=ghp_xxx"
# With a token: 5,000 req/hr per token. Anonymous: 60 req/hr per IP.
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


@app.function_name(name="HelloWorld")
@app.route(route="HelloWorld", methods=["GET", "POST"])
def hello_world(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("HelloWorld invoked (method=%s, instance=%s)", req.method, _INSTANCE_ID)

    # Parse JSON body if present; tolerate empty / non-JSON bodies.
    body: dict = {}
    raw = req.get_body()
    if raw:
        try:
            body = req.get_json()
        except ValueError:
            logging.warning("Request body was not valid JSON; ignoring.")
            body = {"_raw": raw.decode("utf-8", errors="replace")[:200]}

    # Allow query-string overrides for quick browser tests.
    name = body.get("name") or req.params.get("name") or "world"
    items = body.get("items") or []

    response = {
        "ok": True,
        "name": name,
        "message": f"Hello, {name}!",
        "item_count": len(items) if isinstance(items, list) else 0,
        "sum": sum(x for x in items if isinstance(x, (int, float))) if isinstance(items, list) else None,
        "received": body,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "instance_id": _INSTANCE_ID,
        "function_app": os.environ.get("WEBSITE_SITE_NAME", "local"),
    }

    return func.HttpResponse(
        json.dumps(response),
        status_code=200,
        mimetype="application/json",
    )


@app.function_name(name="GetRepoInfo")
@app.route(route="GetRepoInfo", methods=["GET", "POST"])
def get_repo_info(req: func.HttpRequest) -> func.HttpResponse:
    """
    Calls the GitHub REST API and returns curated metadata for a public repo.

    Request (POST or query string):
        { "owner": "Azure", "repo": "azure-kusto-spark" }

    Response (200):
        {
            "ok": true,
            "name": "Azure/azure-kusto-spark",
            "description": "...",
            "stars": 248,
            "forks": 113,
            "language": "Scala",
            "license": "Apache-2.0",
            "topics": [...],
            "updated_at": "2026-05-27T...",
            ...
            "source": "github-api",
            "fetched_at": "2026-05-28T..."
        }

    Errors:
        400 - missing owner/repo
        404 - repo not found
        429 - GitHub rate limit hit (set GITHUB_TOKEN app setting)
        502 - upstream GitHub API error
    """
    logging.info("GetRepoInfo invoked (method=%s, instance=%s)", req.method, _INSTANCE_ID)

    # Accept input from JSON body OR query string
    body: dict = {}
    if req.get_body():
        try:
            body = req.get_json()
        except ValueError:
            body = {}

    owner = (body.get("owner") or req.params.get("owner") or "").strip()
    repo = (body.get("repo") or req.params.get("repo") or "").strip()

    if not owner or not repo:
        return _json_response(
            {"ok": False, "error": "Both 'owner' and 'repo' are required"},
            status_code=400,
        )

    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "NotebookChain-Function",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if _GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {_GITHUB_TOKEN}"

    url = f"https://api.github.com/repos/{owner}/{repo}"

    try:
        r = requests.get(url, headers=headers, timeout=15)
    except requests.RequestException as e:
        return _json_response(
            {"ok": False, "error": f"Network error reaching GitHub: {type(e).__name__}: {e}"},
            status_code=502,
        )

    rate_remaining = r.headers.get("X-RateLimit-Remaining")
    rate_reset = r.headers.get("X-RateLimit-Reset")

    if r.status_code == 404:
        return _json_response(
            {"ok": False, "error": f"Repository '{owner}/{repo}' not found",
             "rate_limit_remaining": rate_remaining},
            status_code=404,
        )

    if r.status_code == 403 and (rate_remaining == "0" or "rate limit" in r.text.lower()):
        return _json_response(
            {"ok": False,
             "error": "GitHub rate limit exceeded. "
                      "Set the GITHUB_TOKEN app setting to raise the limit to 5,000/hr.",
             "rate_limit_remaining": rate_remaining,
             "rate_limit_reset": rate_reset},
            status_code=429,
        )

    if not r.ok:
        return _json_response(
            {"ok": False,
             "error": f"GitHub API returned HTTP {r.status_code}: {r.text[:200]}"},
            status_code=502,
        )

    data = r.json()
    license_info = data.get("license") or {}
    result = {
        "ok": True,
        "owner": owner,
        "repo": repo,
        "name": data.get("full_name"),
        "description": data.get("description"),
        "stars": data.get("stargazers_count"),
        "forks": data.get("forks_count"),
        "watchers": data.get("subscribers_count"),
        "open_issues": data.get("open_issues_count"),
        "size_kb": data.get("size"),
        "language": data.get("language"),
        "license": license_info.get("spdx_id"),
        "default_branch": data.get("default_branch"),
        "topics": data.get("topics", []),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "pushed_at": data.get("pushed_at"),
        "html_url": data.get("html_url"),
        "archived": data.get("archived"),
        "fork": data.get("fork"),
        "source": "github-api",
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rate_limit_remaining": rate_remaining,
        "instance_id": _INSTANCE_ID,
    }
    return _json_response(result, status_code=200)


@app.function_name(name="Health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Anonymous liveness probe — handy for monitoring."""
    return _json_response(
        {"ok": True, "instance_id": _INSTANCE_ID,
         "github_token_configured": bool(_GITHUB_TOKEN)},
        status_code=200,
    )


def _json_response(payload: dict, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload),
        status_code=status_code,
        mimetype="application/json",
    )

