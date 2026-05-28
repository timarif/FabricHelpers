# HelloWorld Azure Function (Python v2)

The function the NotebookChain notebooks call.

## What it does

`POST /api/HelloWorld` — echoes the JSON payload, adds a few computed fields, returns the function instance id (useful for load-test analysis):

```json
{
  "ok": true,
  "name": "Fabric",
  "message": "Hello, Fabric!",
  "item_count": 3,
  "sum": 6,
  "received": { "name": "Fabric", "items": [1,2,3] },
  "received_at": "2026-05-28T17:42:11.123456+00:00",
  "instance_id": "abc12345",
  "function_app": "my-fn-app"
}
```

Also exposes `GET /api/health` (anonymous) for liveness probes.

## Prerequisites

| Tool | Install |
|---|---|
| Python 3.10/3.11 | https://www.python.org/downloads/ |
| Azure Functions Core Tools v4 | `npm i -g azure-functions-core-tools@4 --unsafe-perm true` |
| Azure CLI | https://learn.microsoft.com/cli/azure/install-azure-cli |

## Run locally

```bash
cd Misc/NotebookChain/function
cp local.settings.json.template local.settings.json   # never commit local.settings.json
python -m venv .venv
.\.venv\Scripts\Activate.ps1                          # Windows
# or: source .venv/bin/activate                       # Linux/Mac
pip install -r requirements.txt
func start
```

Test it:

```bash
curl -X POST http://localhost:7071/api/HelloWorld `
  -H "Content-Type: application/json" `
  -d '{"name":"Fabric","items":[1,2,3]}'
```

## Deploy to Azure

```bash
# One-time: create the function app (consumption plan, Linux, Python 3.11)
RG=fabric-samples-rg
LOC=westus3
STG=fnsamplestor$RANDOM        # storage account name must be globally unique
APP=fn-notebookchain-$RANDOM   # function app name must be globally unique

az group create -n $RG -l $LOC
az storage account create -n $STG -g $RG -l $LOC --sku Standard_LRS
az functionapp create -n $APP -g $RG --storage-account $STG `
    --consumption-plan-location $LOC `
    --runtime python --runtime-version 3.11 --functions-version 4 --os-type Linux

# Deploy the code
func azure functionapp publish $APP

# Grab the function URL + key for the notebooks
echo "function_url = https://$APP.azurewebsites.net/api/HelloWorld"
az functionapp keys list -n $APP -g $RG --query "functionKeys.default" -o tsv
```

Paste those two values into:
- `notebooks/01-parent-orchestrator.ipynb` (cell 2) — for the single-call sample
- `notebooks/03-loadbalancer-orchestrator.ipynb` (cell 2) — for the 5,000-call load test

## Auth modes

| Mode | How callers authenticate | Best for |
|---|---|---|
| **Function key** (default in code) | `x-functions-key` header | Quick samples, internal tools |
| **Entra (Easy Auth)** | `Authorization: Bearer <token>` | Production — set up via `az webapp auth update` and uncomment Option B in `02-child-call-azure-function.ipynb` |

## Scaling notes (relevant for the load-test notebooks)

- **Consumption plan** scales out automatically based on incoming HTTP rate. Cold-start latency on first instances will show up as p95/p99 spikes in the first batch of the load test.
- For consistent latency under load, use a **Premium plan** with `WEBSITE_CONTENTOVERVNET=1` + pre-warmed instances:
  ```bash
  az functionapp plan create -n my-premium-plan -g $RG -l $LOC \
      --sku EP1 --min-instances 2 --max-burst 20 --is-linux
  ```
- The load-test orchestrator sends 250 concurrent requests (5 spokes × 50 threads). Functions on consumption typically handles this with 5–10 instances.
