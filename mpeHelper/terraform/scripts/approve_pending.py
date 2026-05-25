#!/usr/bin/env python3
"""Post-apply approval helper: approve Pending Private Endpoint Connections.

After `terraform apply` creates Managed Private Endpoints on the Fabric side,
the corresponding Private Endpoint Connections (PECs) on the target Azure
resources land in *Pending* state.  This script finds those PECs and approves
them via the Azure Resource Manager REST API.

Usage
-----
  # Approve all Pending PECs for resources in terraform.tfvars.json
  python approve_pending.py --tfvars-file terraform.tfvars.json

  # Scope to a specific run_label (only PECs whose description starts with
  # "[run=<label>]" are approved — mirrors the notebook's marker matching)
  python approve_pending.py --tfvars-file terraform.tfvars.json --run-label 2026-01-15_10-00-00

  # Dry-run: print what would be approved without making any changes
  python approve_pending.py --tfvars-file terraform.tfvars.json --dry-run

Authentication
--------------
ARM token resolution order:
  1. ARM_TOKEN env var (pre-acquired bearer token)
  2. azure-identity DefaultAzureCredential (env vars, workload identity, CLI …)
  3. az account get-access-token --resource https://management.azure.com
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
from typing import Any

ARM_BASE = "https://management.azure.com"

# ---------------------------------------------------------------------------
# api-version dispatch (mirrors _PEC_API_VERSIONS in the notebook)
# ---------------------------------------------------------------------------
_PEC_API_VERSIONS: dict[str, str] = {
    "Microsoft.Storage/storageAccounts": "2023-05-01",
    "Microsoft.Sql/servers": "2023-08-01-preview",
    "Microsoft.KeyVault/vaults": "2023-07-01",
    "Microsoft.DocumentDB/databaseAccounts": "2023-04-15",
    "Microsoft.EventHub/namespaces": "2024-01-01",
    "Microsoft.ServiceBus/namespaces": "2022-10-01-preview",
    "Microsoft.Synapse/workspaces": "2021-06-01",
    "Microsoft.Search/searchServices": "2023-11-01",
    "Microsoft.CognitiveServices/accounts": "2023-05-01",
    "Microsoft.AppConfiguration/configurationStores": "2023-03-01",
    "Microsoft.Web/sites": "2023-12-01",
    "Microsoft.ContainerRegistry/registries": "2023-11-01-preview",
    "Microsoft.DataFactory/factories": "2018-06-01",
    "Microsoft.Purview/accounts": "2021-12-01",
}
_PEC_DEFAULT_API_VERSION = "2023-09-01"


def _rp_from_resource_id(rid: str) -> str | None:
    """Extract 'Microsoft.X/typeY' from an ARM resource ID."""
    if not rid:
        return None
    parts = rid.split("/providers/", 1)
    if len(parts) < 2:
        return None
    seg = parts[1].split("/")
    if len(seg) < 2:
        return None
    return f"{seg[0]}/{seg[1]}"


def _pec_api_version(rid: str) -> tuple[str, str | None]:
    rp = _rp_from_resource_id(rid)
    return _PEC_API_VERSIONS.get(rp or "", _PEC_DEFAULT_API_VERSION), rp


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def get_arm_token(arm_base: str = ARM_BASE) -> str:
    """Acquire an ARM bearer token.

    Tries (in order):
      1. ARM_TOKEN env var
      2. azure-identity DefaultAzureCredential
      3. az account get-access-token
    """
    tok = os.environ.get("ARM_TOKEN")
    if tok:
        return tok.strip()

    arm_scope = arm_base.rstrip("/") + "/.default"

    # Try azure-identity (optional dependency — import lazily)
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore[import]

        cred = DefaultAzureCredential()
        token_response = cred.get_token(arm_scope)
        if token_response and token_response.token:
            return token_response.token
    except ImportError:
        pass  # azure-identity not installed — fall through to az CLI
    except Exception as exc:  # noqa: BLE001 — covers CredentialUnavailableError and similar
        print(
            f"  ! azure-identity DefaultAzureCredential failed: {exc}",
            file=sys.stderr,
        )

    # az CLI fallback
    try:
        out = subprocess.check_output(
            [
                "az",
                "account",
                "get-access-token",
                "--resource",
                arm_base.rstrip("/"),
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
            "Could not acquire an ARM token. "
            "Install azure-identity, set ARM_TOKEN, or run `az login`."
        ) from exc

    raise RuntimeError(
        "az account get-access-token returned an empty token. "
        "Run `az login` and retry."
    )


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _req(
    method: str,
    url: str,
    token: str,
    body: dict[str, Any] | None = None,
    max_retries: int = 5,
) -> tuple[int, Any]:
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
# PEC helpers
# ---------------------------------------------------------------------------

def list_pecs(
    target_resource_id: str,
    token: str,
    arm_base: str = ARM_BASE,
) -> tuple[int, list[dict] | dict, str | None, str]:
    """LIST privateEndpointConnections on a target Azure resource.

    Returns (status, payload, rp, api_version).
    On 200, payload is a list; otherwise an error dict.
    """
    api, rp = _pec_api_version(target_resource_id)
    url: str | None = (
        f"{arm_base}{target_resource_id}/privateEndpointConnections"
        f"?api-version={api}"
    )
    out: list[dict] = []
    while url:
        status, data = _req("GET", url, token)
        if status != 200:
            return status, data, rp, api
        out.extend(data.get("value", []))
        url = data.get("nextLink")
    return 200, out, rp, api


def approve_pec(
    target_resource_id: str,
    pec_name: str,
    token: str,
    description: str = "Approved by approve_pending.py",
    api_version: str | None = None,
    arm_base: str = ARM_BASE,
) -> tuple[int, dict]:
    """PUT Approved on a single privateEndpointConnection."""
    if api_version is None:
        api_version, _ = _pec_api_version(target_resource_id)
    url = (
        f"{arm_base}{target_resource_id}/privateEndpointConnections"
        f"/{pec_name}?api-version={api_version}"
    )
    body = {
        "properties": {
            "privateLinkServiceConnectionState": {
                "status": "Approved",
                "description": description,
            }
        }
    }
    return _req("PUT", url, token, body=body)


# ---------------------------------------------------------------------------
# Core approval logic
# ---------------------------------------------------------------------------

def _pec_is_pending(pec: dict) -> bool:
    state = (
        pec.get("properties", {})
        .get("privateLinkServiceConnectionState", {})
        .get("status", "")
    )
    return state.lower() == "pending"


def _pec_matches_run_label(pec: dict, run_label: str) -> bool:
    if not run_label:
        return True
    desc = (
        pec.get("properties", {})
        .get("privateLinkServiceConnectionState", {})
        .get("description", "")
    )
    return f"[run={run_label}]" in desc


def approve_pending_for_resources(
    target_resource_ids: list[str],
    token: str,
    run_label: str = "",
    approve_description: str = "Approved by approve_pending.py",
    dry_run: bool = False,
    arm_base: str = ARM_BASE,
) -> list[dict]:
    """Find and approve Pending PECs across a list of target resources.

    Returns a list of result dicts (one per PEC processed).
    """
    results: list[dict] = []

    for rid in target_resource_ids:
        print(f"  resource: {rid}", file=sys.stderr)
        status, payload, rp, api = list_pecs(rid, token, arm_base)
        if status != 200:
            print(f"    ! LIST failed HTTP {status} — skipping", file=sys.stderr)
            results.append({"resource": rid, "status": status, "error": payload})
            continue

        pecs: list[dict] = payload  # type: ignore[assignment]
        pending = [
            p
            for p in pecs
            if _pec_is_pending(p) and _pec_matches_run_label(p, run_label)
        ]
        print(
            f"    {len(pecs)} PEC(s) total, {len(pending)} pending"
            + (f" matching run_label={run_label!r}" if run_label else ""),
            file=sys.stderr,
        )

        for pec in pending:
            pec_name = pec.get("name", "")
            pec_id = pec.get("id", "")
            print(f"    approving: {pec_name}", file=sys.stderr)
            if dry_run:
                results.append(
                    {"resource": rid, "pec_name": pec_name, "pec_id": pec_id, "status": "dry-run"}
                )
                continue
            ap_status, ap_body = approve_pec(
                rid, pec_name, token,
                description=approve_description,
                api_version=api,
                arm_base=arm_base,
            )
            print(f"      → HTTP {ap_status}", file=sys.stderr)
            results.append(
                {
                    "resource": rid,
                    "pec_name": pec_name,
                    "pec_id": pec_id,
                    "status": ap_status,
                    "response": ap_body,
                }
            )

    return results


# ---------------------------------------------------------------------------
# tfvars reader (extracts unique target_resource_ids)
# ---------------------------------------------------------------------------

def load_target_resource_ids(tfvars_path: Path) -> list[str]:
    """Parse terraform.tfvars.json and return unique target_resource_ids."""
    data = json.loads(tfvars_path.read_text(encoding="utf-8"))
    endpoints: dict = data.get("managed_private_endpoints", {})
    seen: set[str] = set()
    out: list[str] = []
    for entry in endpoints.values():
        rid = entry.get("target_resource_id", "")
        if rid and rid not in seen:
            seen.add(rid)
            out.append(rid)
    return out


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Approve Pending Private Endpoint Connections after "
            "`terraform apply`."
        )
    )
    parser.add_argument(
        "--tfvars-file",
        default="terraform.tfvars.json",
        metavar="FILE",
        help=(
            "Path to terraform.tfvars.json generated by import_existing.py "
            "or written manually (default: ./terraform.tfvars.json)."
        ),
    )
    parser.add_argument(
        "--target-resource-ids",
        nargs="*",
        metavar="ARM_ID",
        help=(
            "Explicit ARM resource IDs to check. "
            "Overrides IDs read from --tfvars-file."
        ),
    )
    parser.add_argument(
        "--run-label",
        default="",
        metavar="LABEL",
        help=(
            "Only approve PECs whose description contains [run=<LABEL>]. "
            "Mirrors the notebook's run-scoped approval."
        ),
    )
    parser.add_argument(
        "--approve-description",
        default="Approved by approve_pending.py",
        metavar="TEXT",
        help="Description written into the PEC approval.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be approved without making any changes.",
    )
    parser.add_argument(
        "--arm-base",
        default=ARM_BASE,
        metavar="URL",
        help=f"Azure ARM base URL (default: {ARM_BASE}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.target_resource_ids:
        target_ids = args.target_resource_ids
    else:
        tfvars_path = Path(args.tfvars_file).expanduser().resolve()
        if not tfvars_path.exists():
            print(
                f"Error: {tfvars_path} not found. "
                "Pass --target-resource-ids or --tfvars-file.",
                file=sys.stderr,
            )
            return 1
        target_ids = load_target_resource_ids(tfvars_path)
        print(
            f"Loaded {len(target_ids)} unique target resource(s) from {tfvars_path}",
            file=sys.stderr,
        )

    if not target_ids:
        print("No target resources to process.", file=sys.stderr)
        return 0

    print("Acquiring ARM token …", file=sys.stderr)
    token = get_arm_token(args.arm_base)
    print("  token acquired", file=sys.stderr)

    if args.dry_run:
        print("\n[DRY-RUN] No approvals will be sent.\n", file=sys.stderr)

    results = approve_pending_for_resources(
        target_ids,
        token,
        run_label=args.run_label,
        approve_description=args.approve_description,
        dry_run=args.dry_run,
        arm_base=args.arm_base,
    )

    approved = [r for r in results if isinstance(r.get("status"), int) and 200 <= r["status"] < 300]
    skipped_dry = [r for r in results if r.get("status") == "dry-run"]
    failed = [
        r for r in results
        if r.get("status") not in ("dry-run",)
        and not (isinstance(r.get("status"), int) and 200 <= r["status"] < 300)
    ]

    if args.dry_run:
        print(f"\nDry-run: {len(skipped_dry)} PEC(s) would be approved.", file=sys.stderr)
    else:
        print(
            f"\nApproved: {len(approved)}  Failed: {len(failed)}",
            file=sys.stderr,
        )

    if failed:
        for r in failed:
            print(f"  FAILED — {r}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
