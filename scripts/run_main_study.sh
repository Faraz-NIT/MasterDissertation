#!/usr/bin/env bash
# Parallel, resumable runner for one study config. Seeds are dealt round-robin to WORKERS processes (default 4), each
# writing <output>_workers/w<k> at low priority so the machine stays usable; run again to resume after an interruption;
# when every worker is done the folders are merged into <output> by scripts/merge_studies.py.
#   scripts/run_main_study.sh configs/main_study_stage1.yaml
#   WORKERS=6 scripts/run_main_study.sh configs/main_study_stage1.yaml
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python}; CFG=${1:-configs/main_study_stage1.yaml}; WORKERS=${WORKERS:-4}
export PYTHONUNBUFFERED=1 OMP_NUM_THREADS=${OMP_NUM_THREADS:-2} MKL_NUM_THREADS=${MKL_NUM_THREADS:-2}
OUT=$($PY -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['output'])" "$CFG")
NAME=$(basename "$OUT"); mkdir -p results/logs "${OUT}_workers"
mapfile -t SEEDS < <($PY -c "import yaml,sys;[print(s) for s in yaml.safe_load(open(sys.argv[1]))['seeds']]" "$CFG")
echo "=== $NAME: ${#SEEDS[@]} seeds over $WORKERS workers ($(date +%F' '%T))"
pids=()
for k in $(seq 0 $((WORKERS-1))); do
  mine=(); for i in "${!SEEDS[@]}"; do [ $((i % WORKERS)) -eq "$k" ] && mine+=("${SEEDS[$i]}"); done
  [ ${#mine[@]} -eq 0 ] && continue
  echo "worker $k: seeds ${mine[*]}"
  nice -n 10 $PY -m ega run --config "$CFG" --seeds "${mine[@]}" --output "${OUT}_workers/w$k" --resume \
    >> "results/logs/${NAME}_w$k.log" 2>&1 &
  pids+=($!)
done
fail=0; for pid in "${pids[@]}"; do wait "$pid" || fail=1; done
if [ $fail -ne 0 ]; then echo "=== $NAME: a worker failed ($(date +%T)); fix and run again to resume"; exit 1; fi
$PY scripts/merge_studies.py --config "$CFG" --workers "${OUT}_workers" --out "$OUT" && $PY -m ega report --results "$OUT"
echo "=== $NAME: done ($(date +%F' '%T))"
