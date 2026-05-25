#!/usr/bin/env python3
"""Bootstrap script: discover existing MPEs and generate Terraform import artefacts.

Calls the Fabric REST API to list Managed Private Endpoints in one or more
workspaces, then writes:

  imports.tf              — Terraform import blocks (requires Terraform >= 1.5)
  terraform.tfvars.json   — managed_private_endpoints variable ready for apply

Run once to bring existing MPEs under Terraform management without recreating
them.  After running, execute:

  terraform init
  terraform plan   # should show zero drift once state is imported

Usage
-----
  # All visible workspaces
  python import_existing.py

  # Specific workspaces
  python import_existing.py --workspace-ids ws-guid-1 ws-guid-2

  # Write to a different directory
  python import_existing.py --output-dir /path/to/tf/root

Authentication
--------------
Fabric token resolution order (mirrors the notebook's get_token()):
  1. FABRIC_TOKEN env var
  2. az account get-access-token --resource https://api.fabric.microsoft.com
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

FABRIC_BASE = "https://api.fabric.microsoft.com"

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_fabric_token(fabric_base: str = FABRIC_BASE) -> str:
    """Acquire a Fabric bearer token.

    Tries (in order):
      1. FABRIC_TOKEN env var
      2. az account get-access-token
    """
    tok = os.environ.get("FABRIC_TOKEN")
    if tok:
        return tok.strip()

    try:
        out = subprocess.check_output(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                fabric_base,
                "--query",
                "accessToken",
                "-o",
                "tsv",
            ],
            stderr=subprocess.PIPE,
            text=True,
        ).strip()
        if out:
            return out
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        raise RuntimeError(
            "Could not acquire a Fabric token. "
            "Set FABRIC_TOKEN or run `az login`."
        ) from exc

    raise RuntimeError(
        "az account get-access-token returned an empty token. "
        "Run `az login` and retry."
    )


# ---------------------------------------------------------------------------
# HTTP helpers (mirrors the notebook's _req pattern)
# ---------------------------------------------------------------------------

def _req(
    method: str,
    url: str,
    token: str,
    body: dict | None = None,
    max_retries: int = 5,
) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    headers: dict[str, str] = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"

    for attempt in range(max_retries):
        req = urllib.request.Request(
            url, data=data, method=method, headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                return resp.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = int(exc.headers.get("Retry-After", "5"))
                print(f"  ! 429 rate-limited — sleeping {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            if 500 <= exc.code < 600 and attempt + 1 < max_retries:
                time.sleep(min(2**attempt, 30))
                continue
            err_body = exc.read().decode("utf-8", errors="replace")
            try:
                err_parsed = json.loads(err_body)
            except json.JSONDecodeError:
                err_parsed = {"raw": err_body}
            return exc.code, err_parsed
        except urllib.error.URLError:
            if attempt + 1 < max_retries:
                time.sleep(2**attempt)
                continue
            raise

    return 0, {"error": "exhausted retries"}


# ---------------------------------------------------------------------------
# Fabric API calls
# ---------------------------------------------------------------------------

def list_workspaces(token: str, fabric_base: str = FABRIC_BASE) -> list[dict]:
    """Return all workspaces visible to the caller."""
    url: str | None = f"{fabric_base}/v1/workspaces"
    out: list[dict] = []
    while url:
        status, data = _req("GET", url, token)
        if status != 200:
            raise RuntimeError(f"List workspaces failed: HTTP {status} — {data}")
        out.extend(data.get("value", []))
        ct = data.get("continuationToken")
        url = (
            f"{fabric_base}/v1/workspaces"
            f"?continuationToken={urllib.parse.quote(ct)}"
        ) if ct else None
    return out


def list_mpes(
    workspace_id: str,
    token: str,
    fabric_base: str = FABRIC_BASE,
) -> list[dict]:
    """Return all MPEs in a single workspace (empty list on permission error)."""
    base = f"{fabric_base}/v1/workspaces/{workspace_id}/managedPrivateEndpoints"
    url: str | None = base
    out: list[dict] = []
    while url:
        status, data = _req("GET", url, token)
        if status == 200:
            out.extend(data.get("value", []))
            ct = data.get("continuationToken")
            url = (
                f"{base}?continuationToken={urllib.parse.quote(ct)}"
            ) if ct else None
        else:
            print(
                f"  ! workspace {workspace_id}: HTTP {status} — skipping",
                file=sys.stderr,
            )
            return []
    return out


# ---------------------------------------------------------------------------
# Inventory builder
# ---------------------------------------------------------------------------

def build_inventory(
    workspace_ids: list[str] | None,
    token: str,
    fabric_base: str = FABRIC_BASE,
) -> list[dict]:
    """Discover MPEs across workspaces.

    If *workspace_ids* is None or empty, every visible workspace is queried.
    Returns a flat list of dicts with normalised keys.
    """
    if workspace_ids:
        workspaces = [{"id": wid, "displayName": wid} for wid in workspace_ids]
    else:
        print("Listing all visible workspaces …", file=sys.stderr)
        workspaces = list_workspaces(token, fabric_base)
        print(f"  found {len(workspaces)} workspace(s)", file=sys.stderr)

    inventory: list[dict] = []
    for ws in workspaces:
        wid = ws["id"]
        wname = ws.get("displayName", wid)
        print(f"  scanning {wname} ({wid}) …", file=sys.stderr)
        mpes = list_mpes(wid, token, fabric_base)
        print(f"    {len(mpes)} MPE(s)", file=sys.stderr)
        for mpe in mpes:
            inventory.append(
                {
                    "workspace_id": wid,
                    "workspace_name": wname,
                    "mpe_id": mpe.get("id", ""),
                    "name": mpe.get("name", ""),
                    "target_resource_id": mpe.get(
                        "targetPrivateLinkResourceId", ""
                    ),
                    "target_subresource_type": mpe.get(
                        "targetSubresourceType", None
                    ),
                    "request_message": mpe.get("requestMessage", ""),
                    "provisioning_state": mpe.get("provisioningState", ""),
                }
            )

    return inventory


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _logical_key(workspace_id: str, name: str) -> str:
    """Produce a stable Terraform map key from (workspace_id, name)."""
    safe_name = name.replace("-", "_").replace(" ", "_")
    short_ws = workspace_id.replace("-", "")[:8]
    return f"ws_{short_ws}_{safe_name}"


def write_imports_tf(inventory: list[dict], output_dir: Path) -> Path:
    """Write imports.tf with one import block per discovered MPE."""
    lines: list[str] = [
        "# Auto-generated by import_existing.py — do not edit manually.\n",
        "# Re-run import_existing.py after adding or removing MPEs.\n",
        "\n",
    ]
    for entry in inventory:
        key = _logical_key(entry["workspace_id"], entry["name"])
        # Terraform import ID format for fabric_workspace_managed_private_endpoint
        # is: <workspace_id>/<mpe_id>
        tf_id = f"{entry['workspace_id']}/{entry['mpe_id']}"
        lines += [
            "import {\n",
            f'  to = module.mpe["{key}"].fabric_workspace_managed_private_endpoint.this\n',
            f'  id = "{tf_id}"\n',
            "}\n",
            "\n",
        ]

    out_path = output_dir / "imports.tf"
    out_path.write_text("".join(lines), encoding="utf-8")
    return out_path


def write_tfvars_json(inventory: list[dict], output_dir: Path) -> Path:
    """Write terraform.tfvars.json populated with the discovered endpoints."""
    endpoints: dict[str, dict] = {}
    for entry in inventory:
        key = _logical_key(entry["workspace_id"], entry["name"])
        endpoints[key] = {
            "workspace_id": entry["workspace_id"],
            "name": entry["name"],
            "target_resource_id": entry["target_resource_id"],
            "request_message": entry["request_message"] or "Imported by import_existing.py",
        }
        if entry.get("target_subresource_type"):
            endpoints[key]["target_subresource_type"] = entry["target_subresource_type"]

    payload = {"managed_private_endpoints": endpoints}
    out_path = output_dir / "terraform.tfvars.json"
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Discover existing Fabric Managed Private Endpoints and generate "
            "Terraform import artefacts."
        )
    )
    parser.add_argument(
        "--workspace-ids",
        nargs="*",
        metavar="GUID",
        help=(
            "One or more workspace GUIDs to scan. "
            "Omit to scan all visible workspaces."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        metavar="DIR",
        help="Directory to write imports.tf and terraform.tfvars.json (default: cwd).",
    )
    parser.add_argument(
        "--fabric-base",
        default=FABRIC_BASE,
        metavar="URL",
        help=f"Fabric REST API base URL (default: {FABRIC_BASE}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("Acquiring Fabric token …", file=sys.stderr)
    token = get_fabric_token(args.fabric_base)
    print("  token acquired", file=sys.stderr)

    inventory = build_inventory(args.workspace_ids, token, args.fabric_base)
    print(f"\nTotal MPEs found: {len(inventory)}", file=sys.stderr)

    if not inventory:
        print("Nothing to import.", file=sys.stderr)
        return 0

    imports_path = write_imports_tf(inventory, output_dir)
    tfvars_path = write_tfvars_json(inventory, output_dir)

    print(f"\nWrote: {imports_path}", file=sys.stderr)
    print(f"Wrote: {tfvars_path}", file=sys.stderr)
    print(
        "\nNext steps:\n"
        "  terraform init\n"
        "  terraform plan   # should show zero drift after import",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
