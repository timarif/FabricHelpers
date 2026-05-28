# NotebookChain — Fabric notebooks → Azure Function

End-to-end sample showing how Fabric notebooks orchestrate calls to an HTTP-triggered Azure Function, with two patterns:

1. **Single call** — parent notebook → reusable child notebook → function (`01-` and `02-`)
2. **Load-balanced fan-out** — orchestrator → 5 spoke notebooks in parallel → 5,000 function calls (`03-` and `04-loadgen-spoke-{A..E}`)
3. **Function-as-API-proxy** — notebook → function → public API (GitHub) → notebook displays results as Spark DataFrame (`05-`)

```
Misc/NotebookChain/
├── README.md                                       # this file
├── notebooks/                                      # Fabric notebooks (import into a workspace)
│   ├── 01-parent-orchestrator.ipynb                #   pattern 1: parent
│   ├── 02-child-call-azure-function.ipynb          #   pattern 1: reusable child (the "hub")
│   ├── 03-loadbalancer-orchestrator.ipynb          #   pattern 2: fan-out launcher
│   ├── 04-loadgen-spoke-{A,B,C,D,E}.ipynb          #   pattern 2: 5 parallel spokes (1k calls each)
│   └── 05-fetch-data-via-function.ipynb            #   pattern 3: GitHub API -> DataFrame
└── function/                                       # the Azure Function the notebooks call
    ├── README.md                                   #   deploy + local-run instructions
    ├── function_app.py                             #   Python v2: HelloWorld + GetRepoInfo + health
    ├── host.json
    ├── requirements.txt
    ├── local.settings.json.template
    └── .funcignore
```

**Start here:** [`function/README.md`](function/README.md) to deploy (or run locally with `func start`), then paste the URL + key into the orchestrator notebooks.

---

## Pattern 1 — Single call (parent → child → function)

```
01-parent-orchestrator.ipynb
        │  notebookutils.notebook.run(child, arguments={...})
        ▼
02-child-call-azure-function.ipynb
        │  requests.post(function_url, headers={x-functions-key: ...})
        ▼
Azure Function (HTTP trigger)
        │  returns JSON
        ▼
child returns JSON via notebookutils.notebook.exit(...)
        ▼
parent parses + asserts result["status"] == "ok"
```

## Setup

1. Deploy (or `func start` locally) the function in `function/` — see [`function/README.md`](function/README.md).
2. Import both notebooks into the **same Fabric workspace**.
3. Open `01-parent-orchestrator.ipynb` and edit cell 2:
   - `function_url` — your function's HTTPS URL
   - `function_key` — value from the function's "Function Keys" blade (default auth) **OR** switch the child to Entra auth (see Option B in cell 3 of the child)
   - `payload` — whatever JSON your function expects in the request body
3. Run the parent top-to-bottom.

## Key contracts

| Concern | How it's handled |
|---|---|
| **Param passing** | Parent uses `notebook.run(..., arguments=child_params)`. Child has a cell tagged `parameters` whose variables are overwritten at runtime. |
| **Return value** | Child calls `notebook.exit(json.dumps(result))`. Parent receives the string and `json.loads` it. |
| **Auth (function)** | Default: `x-functions-key` header. Alternative (commented in child cell 3): Entra bearer token via `notebookutils.credentials.getToken(audience)`. |
| **Error propagation** | Child wraps the HTTP call in try/except, always returns a JSON envelope with `status`/`http_status`/`error`/`response`. Parent asserts `status == "ok"` so a failed function call fails the parent run. |
| **Timeouts** | Parent: `timeoutSeconds=300` on `notebook.run`. Child: `timeout=60` on the `requests.post`. Tune both. |

## When to use this pattern

- **Reusable callouts**: many parent notebooks need to hit the same function — keep the auth/retry logic in one child.
- **Parameter sweeps**: parent loops, calls child many times with different `payload`s.
- **Separation of concerns**: child knows the function; parent knows the business workflow.

## When NOT to use this pattern

- A one-shot call from a single notebook — just inline the `requests.post` in the parent.
- High-volume per-row calls — use a Spark `mapPartitions` UDF inside one notebook instead; spawning child notebooks per call is expensive.

---

# Pattern 2 — Load-balancer fan-out (5,000 calls)

Files: `03-loadbalancer-orchestrator.ipynb` + `04-loadgen-spoke-{A..E}.ipynb`

```
03-loadbalancer-orchestrator
        │  notebookutils.notebook.runMultiple([5 spokes], concurrency=5)
        ▼
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ spoke A  │ spoke B  │ spoke C  │ spoke D  │ spoke E  │   ← 5 sub-sessions
│ 1,000 x  │ 1,000 x  │ 1,000 x  │ 1,000 x  │ 1,000 x  │      in parallel
└────┬─────┴────┬─────┴────┬─────┴────┬─────┴────┬─────┘
     ▼          ▼          ▼          ▼          ▼
              Azure Function (HTTPS, 5,000 total)
```

Each spoke fires 1,000 concurrent HTTPS calls via `ThreadPoolExecutor`, captures per-call latency, and returns aggregated stats (`count_ok`, `count_fail`, `p50/p95/p99 ms`, `throughput_rps`) to the orchestrator via `notebook.exit(json...)`. The orchestrator collects all 5 envelopes and prints a combined latency table.

## Tuning knobs (orchestrator cell 2)

| Knob | Default | What it controls |
|---|---|---|
| `calls_per_spoke` | `1000` | calls each spoke makes |
| `concurrency` | `50` | threads per spoke (so peak concurrent in-flight requests across cluster = 5 × 50 = 250) |
| `request_timeout` | `30s` | per-HTTP-call timeout |
| `spoke_timeout_s` | `1800s` | per-spoke notebook timeout |

## Why direct HTTP, not 5,000 `notebook.run` calls?

Each `notebook.run` spins up a separate Fabric sub-session (tens of seconds of startup). 5,000 sub-sessions would take hours and burn capacity. Direct HTTP calls from threads inside 5 long-running spoke sessions is the correct architecture for load generation.

## Expected output

```
spoke                                ok   fail     p50     p95     p99     rps
--------------------------------------------------------------------------------
04-loadgen-spoke-A                  998      2     142     387     891    19.4
04-loadgen-spoke-B                  999      1     138     401     923    19.6
04-loadgen-spoke-C                 1000      0     145     395     878    19.5
04-loadgen-spoke-D                  997      3     141     412     901    19.3
04-loadgen-spoke-E                 1000      0     139     389     885    19.6
--------------------------------------------------------------------------------
COMBINED                           4994      6     141     398     896    96.7

Total wall time : 51.7s
Success rate    : 99.88%
```

## Capacity gotchas

- **Fabric capacity SKU**: launching 5 spokes in parallel needs enough capacity units for 5 concurrent Spark sessions. F2/F4 may queue them; F8+ runs all 5 immediately.
- **Function app scale**: 250 concurrent requests will trigger Functions to scale out instances. On a Consumption plan, expect cold-start spikes in the first batch (visible in p95/p99).
- **Outbound throttling**: Fabric Spark sessions share an egress pool. If you see SNAT errors in spoke `fail_samples`, drop `concurrency` to 25 or run in stages.
