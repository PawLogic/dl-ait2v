#!/bin/bash
# ============================================================================
# Serverless 端到端测试脚本
#
# 用法:
#   在基线 Pod 上运行:
#     ./test_serverless.sh                    # 全量测试（smoke + 生成）
#     ./test_serverless.sh --smoke-only       # 只跑 smoke test
#
#   测试远程 endpoint:
#     ./test_serverless.sh --endpoint lywcykmmcg3umf
#     ./test_serverless.sh --endpoint lywcykmmcg3umf --workflow my_workflow
# ============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

HANDLER_PORT=8090
SMOKE_ONLY=false
ENDPOINT_ID=""

# 默认测试素材
TEST_IMAGE="https://itchy-lime-q49kq0fex1.edgeone.app/20260310-140254.jpg"
TEST_AUDIO="https://quiet-scarlet-jq6kfzhzdk.edgeone.app/bazooka_19_37.mp3"
TEST_WORKFLOW="workflow_ltx2-3_audio_gen_ui"

while [[ $# -gt 0 ]]; do
    case $1 in
        --smoke-only) SMOKE_ONLY=true; shift ;;
        --endpoint)   ENDPOINT_ID="$2"; shift 2 ;;
        --image)      TEST_IMAGE="$2"; shift 2 ;;
        --audio)      TEST_AUDIO="$2"; shift 2 ;;
        --workflow)   TEST_WORKFLOW="$2"; shift 2 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

# ─── Remote endpoint test (async: run → poll status) ───
if [ -n "$ENDPOINT_ID" ]; then
    if [ -z "${RUNPOD_API_KEY:-}" ]; then
        echo -e "${RED}Error: RUNPOD_API_KEY not set${NC}"
        exit 1
    fi

    API_BASE="https://api.runpod.ai/v2/${ENDPOINT_ID}"
    AUTH="Authorization: Bearer ${RUNPOD_API_KEY}"

    echo -e "${GREEN}Testing endpoint: ${ENDPOINT_ID}${NC}"
    echo "  Workflow: ${TEST_WORKFLOW}"
    echo "  Submitting job..."

    # 1. Submit async job
    SUBMIT=$(curl -s -X POST "${API_BASE}/run" \
        -H "$AUTH" \
        -H "Content-Type: application/json" \
        -d "{\"input\":{\"workflow\":\"${TEST_WORKFLOW}\",\"image_url\":\"${TEST_IMAGE}\",\"audio_url\":\"${TEST_AUDIO}\"}}")

    JOB_ID=$(echo "$SUBMIT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)

    if [ -z "$JOB_ID" ]; then
        echo -e "${RED}Submit failed:${NC}"
        echo "$SUBMIT" | python3 -m json.tool 2>/dev/null || echo "$SUBMIT"
        exit 1
    fi

    echo "  Job ID: $JOB_ID"

    # 2. Poll for completion
    echo "  Waiting for completion..."
    POLL_INTERVAL=10
    MAX_POLLS=120  # 20 minutes max

    for i in $(seq 1 $MAX_POLLS); do
        sleep $POLL_INTERVAL
        STATUS_RESP=$(curl -s "${API_BASE}/status/${JOB_ID}" -H "$AUTH")
        STATUS=$(echo "$STATUS_RESP" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','UNKNOWN'))" 2>/dev/null)

        case "$STATUS" in
            COMPLETED)
                echo -e "  ${GREEN}COMPLETED${NC}"
                echo "$STATUS_RESP" | python3 -c "
import sys, json
d = json.load(sys.stdin)
out = d.get('output', {})
if isinstance(out, dict):
    inner = out.get('output', out)
    for f in inner.get('files', []):
        print(f'  Output: {f.get(\"type\")} -> {f.get(\"url\", \"N/A\")}')
    print(f'  Generation time: {inner.get(\"generation_time\", \"?\")}s')
    print(f'  Status: {out.get(\"status\", \"?\")}')
" 2>/dev/null
                exit 0
                ;;
            FAILED)
                echo -e "  ${RED}FAILED${NC}"
                echo "$STATUS_RESP" | python3 -m json.tool 2>/dev/null || echo "$STATUS_RESP"
                exit 1
                ;;
            IN_QUEUE|IN_PROGRESS)
                ELAPSED=$((i * POLL_INTERVAL))
                printf "  [%ds] %s...\r" "$ELAPSED" "$STATUS"
                ;;
            *)
                echo "  Status: $STATUS"
                ;;
        esac
    done

    echo -e "${RED}Timeout after $((MAX_POLLS * POLL_INTERVAL))s${NC}"
    exit 1
fi

# ─── Local tests (on pod) ───

echo "============================================"
echo " Serverless Test Suite"
echo "============================================"

# Smoke test
echo ""
echo -e "${GREEN}[1/2] Smoke Test${NC}"

source /workspace/venv-cu130/bin/activate

python3 -c "
import sys; sys.path.insert(0, '/workspace/handler')
from rp_handler import list_workflows, load_workflow, find_input_nodes
import requests, os

errors = []

# Workflow discovery
wfs = list_workflows()
print(f'  Workflows: {wfs}')
if not wfs:
    errors.append('No workflows found')

# Load + analyze
for wf_name in wfs:
    try:
        wf = load_workflow(wf_name)
        nodes = find_input_nodes(wf)
        print(f'  {wf_name}: {len(wf)} nodes, inputs={nodes}')
    except Exception as e:
        errors.append(f'{wf_name}: {e}')

# ComfyUI
try:
    r = requests.get('http://127.0.0.1:8188/system_stats', timeout=5)
    print(f'  ComfyUI: {r.status_code}')
except:
    errors.append('ComfyUI not reachable')

# GCS
print(f'  GCS creds: {os.path.exists(\"/workspace/gcs-credentials.json\")}')
if not os.path.exists('/workspace/gcs-credentials.json'):
    errors.append('GCS credentials missing')

if errors:
    print(f'  ERRORS: {errors}')
    sys.exit(1)
print('  SMOKE TEST PASSED')
"

if [ "$SMOKE_ONLY" = true ]; then
    echo -e "${GREEN}Done (smoke only).${NC}"
    exit 0
fi

# Full generation test
echo ""
echo -e "${GREEN}[2/2] Full Generation Test${NC}"
echo "  Starting handler on :${HANDLER_PORT}..."

pkill -f rp_handler 2>/dev/null || true
sleep 1

cd /workspace/handler
nohup python rp_handler.py --rp_serve_api --rp_api_port "$HANDLER_PORT" > /tmp/handler_test.log 2>&1 &
HANDLER_PID=$!
sleep 5

echo "  Sending request (workflow=${TEST_WORKFLOW})..."
RESULT=$(curl -s -X POST "http://127.0.0.1:${HANDLER_PORT}/runsync" \
    -H "Content-Type: application/json" \
    -d "{\"input\":{\"workflow\":\"${TEST_WORKFLOW}\",\"image_url\":\"${TEST_IMAGE}\",\"audio_url\":\"${TEST_AUDIO}\"}}")

kill "$HANDLER_PID" 2>/dev/null || true

STATUS=$(echo "$RESULT" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('output',d).get('status','unknown'))" 2>/dev/null || echo "parse_error")

if [ "$STATUS" = "success" ]; then
    echo -e "  ${GREEN}GENERATION TEST PASSED${NC}"
    echo "$RESULT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
out = d.get('output', d).get('output', {})
for f in out.get('files', []):
    print(f'  Output: {f.get(\"type\")} -> {f.get(\"url\", \"N/A\")}')
print(f'  Generation time: {out.get(\"generation_time\", \"?\")}s')
" 2>/dev/null
else
    echo -e "  ${RED}GENERATION TEST FAILED${NC}"
    echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"
    echo ""
    echo "Handler log:"
    cat /tmp/handler_test.log
    exit 1
fi
