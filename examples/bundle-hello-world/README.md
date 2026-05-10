# bundle-hello-world

Smallest working SatHop bundle. Use it as a smoke test after spinning up an orchestrator + worker, and as a reference when authoring your own.

**What it does.** Reads each text-file input from `$SATHOP_INPUT_DIR`, prepends a one-line header (granule id, batch id, meta tag), and writes `<stem>-tagged.txt` to `$SATHOP_OUTPUT_DIR`. Reports progress checkpoints if `$SATHOP_PROGRESS_URL` is set. stdlib only — no `pip` deps, so the worker reuses its current Python environment instead of building a venv.

See `../../docs/bundle-authoring.md` for the full manifest reference.

## End-to-end

Assumes orchestrator + worker + receiver are running and reachable.

```bash
# 1. Static-validate
sathop-validate-bundle examples/bundle-hello-world

# 2. Zip + upload
sathop-upload-bundle examples/bundle-hello-world \
  --url sathop://TOKEN@orchestrator:8000

# 3. Submit a batch via Web UI ("新建任务"):
#    - 任务包:   hello-world@1.0.0
#    - 数据粒:   granule_id = g1
#                slot=payload  url=https://example.com/hello.txt  filename=hello.txt  product=text/plain
#    - 元数据:   tag = smoke-test
```

After a few seconds, the batch-detail page should show the granule cycling through DOWNLOADING → PROCESSING → UPLOADED → ACKED → DELETED. The receiver ends up with `hello/smoke-test/hello-tagged.txt` under its archive root.

## Standalone debug

Run `run.py` directly without a worker — handy when iterating:

```bash
mkdir -p /tmp/h-in /tmp/h-out
echo "the cake is a lie" > /tmp/h-in/sample.txt

SATHOP_INPUT_DIR=/tmp/h-in \
SATHOP_OUTPUT_DIR=/tmp/h-out \
SATHOP_GRANULE_ID=local-g1 \
SATHOP_BATCH_ID=local-b1 \
SATHOP_META_JSON='{"tag":"local"}' \
  python run.py

cat /tmp/h-out/sample-tagged.txt
# # granule=local-g1 batch=local-b1 tag=local
# the cake is a lie
```

PowerShell equivalent:

```powershell
mkdir -Force C:\tmp\h-in, C:\tmp\h-out | Out-Null
"the cake is a lie" | Set-Content C:\tmp\h-in\sample.txt

$env:SATHOP_INPUT_DIR  = "C:\tmp\h-in"
$env:SATHOP_OUTPUT_DIR = "C:\tmp\h-out"
$env:SATHOP_GRANULE_ID = "local-g1"
$env:SATHOP_BATCH_ID   = "local-b1"
$env:SATHOP_META_JSON  = '{"tag":"local"}'
python run.py
Get-Content C:\tmp\h-out\sample-tagged.txt
```
