"""
HTTP-triggered Azure Function that the NotebookChain sample notebooks call.

Programming model: Python v2 (decorator-based, single file).
Auth level:        function (callers send 'x-functions-key' header).

Endpoint:
    POST/GET  /api/HelloWorld

Request (POST):
    {
        "name":   "Fabric",
        "items":  [1, 2, 3],
        "metadata": { ... }
    }

Response:
    {
        "ok":          true,
        "name":        "Fabric",
        "message":     "Hello, Fabric!",
        "item_count":  3,
        "sum":         6,
        "received":    { ...echo of input... },
        "received_at": "2026-05-28T17:42:11.123456+00:00",
        "instance_id": "abc123..."           # function instance — useful for load tests
    }
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# A per-instance id so load-test callers can see how many function instances
# Azure spun up to handle their traffic. Created once per cold start.
_INSTANCE_ID = uuid.uuid4().hex[:8]


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


@app.function_name(name="Health")
@app.route(route="health", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def health(req: func.HttpRequest) -> func.HttpResponse:
    """Anonymous liveness probe — handy for monitoring."""
    return func.HttpResponse(
        json.dumps({"ok": True, "instance_id": _INSTANCE_ID}),
        status_code=200,
        mimetype="application/json",
    )
