#!/usr/bin/env bash
# Run every experiment that needs no LLM endpoint or Chronos weights, on real M5 data.
# Assumes `pip install -e ".[ml,dev]"` and M5 CSVs in data/raw/m5 (see scripts/fetch_m5.py).
# Each step logs to results/logs/<step>.log; a failing step does not stop the others.
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python}
mkdir -p results/logs results/run_configs
sed 's#^dataset: .*#dataset: data/processed/m5_smoke#' configs/smoke.yaml > results/run_configs/smoke_m5.yaml

step() {
  local name=$1; shift
  if [ -e "results/logs/$name.done" ]; then echo "skip $name (done)"; return; fi
  echo "=== $name: $* ($(date +%T))"
  local t0=$SECONDS
  if "$@" > "results/logs/$name.log" 2>&1; then
    touch "results/logs/$name.done"; echo "    ok in $((SECONDS-t0))s"
  else
    echo "    FAILED in $((SECONDS-t0))s — see results/logs/$name.log"
  fi
}

step tests        $PY -m pytest -q
step demo         $PY -m ega demo --output results/my_demo --days 6
step prep_smoke   $PY -m ega prepare --raw data/raw/m5 --out data/processed/m5_smoke --items 1 --stores CA_1 CA_2
step prep_pilot   $PY -m ega prepare --raw data/raw/m5 --out data/processed/m5 --items 3
step m5_smoke     $PY -m ega run --config results/run_configs/smoke_m5.yaml --output results/m5_smoke
step m5_pilot     $PY -m ega run --config configs/pilot.yaml --output results/m5_pilot
for m in seasonal_naive croston_sba lightgbm deep; do
  step "backtest_$m" $PY -m ega forecast-backtest --config configs/pilot.yaml \
    --model "$m" --origins 1800 1828 --horizon 28 --out "results/forecast_$m.json"
done
step baseline_pilot $PY -m ega run --config configs/deterministic_study.yaml \
  --policies B1 B2 B3 B4 --seeds 7 29 --days 7 --output results/baseline_pilot
step grounding    $PY scripts/grounding_benchmark.py --generate --output results/grounding_templates
step sensitivity  $PY scripts/sensitivity_sweep.py --config results/run_configs/smoke_m5.yaml --output results/sensitivity
step audit_packets $PY -m ega audit-packets --results results/m5_pilot --out results/audit_packets --participants 3
for r in m5_smoke m5_pilot baseline_pilot; do
  [ -d "results/$r" ] && step "report_$r" $PY -m ega report --results "results/$r"
done
echo "=== finished $(date +%T)"
