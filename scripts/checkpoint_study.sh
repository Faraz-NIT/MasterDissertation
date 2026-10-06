#!/usr/bin/env bash
# Save-point loop for a running study: every INTERVAL seconds (default 30 min) merge the completed worker runs into
# the study folder (hard links, partial runs skipped), rebuild the results index and PDF report, and mirror results/
# to BACKUP_DIR. Keeps going until the study driver exits, then does one final pass. Safe to run alongside the study.
#   scripts/checkpoint_study.sh configs/main_study_stage1.yaml
set -u
cd "$(dirname "$0")/.."
PY=${PY:-python}; CFG=${1:-configs/main_study_stage1.yaml}; INTERVAL=${INTERVAL:-1800}
BACKUP_DIR=${BACKUP_DIR:-$HOME/Downloads/ega-results-backup}
OUT=$($PY -c "import yaml,sys;print(yaml.safe_load(open(sys.argv[1]))['output'])" "$CFG")
mkdir -p results/logs "$BACKUP_DIR"
pass() {
  echo "=== checkpoint $(date +%F' '%T): $(ls ${OUT}_workers/w*/*/summary.json 2>/dev/null | wc -l) completed runs"
  $PY scripts/merge_studies.py --config "$CFG" --workers "${OUT}_workers" --out "$OUT" 2>&1 | tail -n 1
  $PY scripts/export_results.py > /dev/null 2>&1 && echo "results index rebuilt"
  $PY scripts/make_report.py --out results/report/pilot_results.pdf > /dev/null 2>&1 && echo "report rebuilt"
  rsync -a --delete --exclude 'logs/*.tmp' results/ "$BACKUP_DIR/results/" && cp -a docs "$BACKUP_DIR/" && echo "mirrored to $BACKUP_DIR"
}
while pgrep -f "run_main_study.sh" > /dev/null; do sleep "$INTERVAL"; pass; done
pass; echo "=== checkpoint loop finished $(date +%F' '%T) (study driver exited)"
