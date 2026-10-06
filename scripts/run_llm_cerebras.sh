#!/usr/bin/env bash
# Second-stage LLM experiments on the Cerebras free tier (about 1M tokens/day for gpt-oss-120b).
# Every step is resumable, so run this once a day until it prints "all steps done":
#   export EGA_LLM_API_KEY='...'   # never commit it
#   scripts/run_llm_cerebras.sh
# A step that stops on the daily quota is retried after QUOTA_WAIT seconds (default 1h), up to MAX_ROUNDS times.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python}
export PYTHONUNBUFFERED=1
QUOTA_WAIT=${QUOTA_WAIT:-3600}
MAX_ROUNDS=${MAX_ROUNDS:-24}
CFG=configs/llm_study.cerebras.yaml
mkdir -p results/logs

if [ -z "${EGA_LLM_API_KEY:-}" ]; then
  echo "EGA_LLM_API_KEY is not set. Export your Cerebras key first; nothing was run." >&2; exit 2
fi

quota_hit() { grep -qiE 'ProviderQuotaExhausted|rate limit|quota' "$1"; }

step() {  # step <name> <command...>: logs to results/logs/<name>.log, marks results/logs/<name>.done on success
  local name=$1; shift
  if [ -e "results/logs/$name.done" ]; then echo "skip $name (done)"; return 0; fi
  local round=0
  while :; do
    round=$((round+1)); echo "=== $name (round $round): $* ($(date +%T))"
    local t0=$SECONDS
    if "$@" >> "results/logs/$name.log" 2>&1; then
      touch "results/logs/$name.done"; echo "    ok in $((SECONDS-t0))s"; return 0
    fi
    if quota_hit "results/logs/$name.log" && [ "$round" -lt "$MAX_ROUNDS" ]; then
      echo "    provider quota/rate limit after $((SECONDS-t0))s; sleeping ${QUOTA_WAIT}s then resuming"
      sleep "$QUOTA_WAIT"
    else
      echo "    FAILED in $((SECONDS-t0))s — see results/logs/$name.log"; return 1
    fi
  done
}

# 1. Does the LLM itself resist a hostile supplier note when the deterministic screen is off? (B4 is the control.)
step llm_injection_unscreened $PY -m ega run --config configs/llm_injection_unscreened.cerebras.yaml --resume

# 2. Fixed-evidence reliability: 30 replications of one B10 decision, only the requested LLM seed varies.
step llm_fixed_evidence $PY scripts/repeat_decision.py \
  --run-dir results/llm_pilot_cerebras/B10__normal__seed42__origin0 --config $CFG \
  --replications 30 --out results/fixed_evidence_cerebras

# 3. Constraint grounding from controlled prose, where the deterministic parser can only escalate.
step llm_grounding_prose $PY scripts/grounding_benchmark.py --corpus examples/grounding_prose.jsonl \
  --llm-config $CFG --output results/grounding_prose_cerebras

# 4. Rebuild the PDF report from whatever is on disk.
step report_stage2 $PY scripts/make_report.py --out results/report/pilot_results.pdf
rm -f results/logs/report_stage2.done  # the report is cheap and should always rebuild on the next pass

for s in llm_injection_unscreened llm_fixed_evidence llm_grounding_prose; do
  [ -e "results/logs/$s.done" ] || { echo "=== not finished: $s ($(date +%T))"; exit 1; }
done
echo "=== all steps done $(date +%T)"
