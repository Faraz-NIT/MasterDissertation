# Numeric-stage storage watcher

```bash
# Discovery and budget snapshot only; does not pack.
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_baseline_storage.py --once

# Enable verified packing and watch every 60 seconds.
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_baseline_storage.py --run
```

The watcher is restricted to main_study_stage1 and
llm_prose_reference_30series in the registered pipeline. It lowers its own nice
priority to 10, sends no process signals, and never restarts jobs. Packing uses
the verified m5_pack_artifacts.py helper under the shared artifact_merge.lock.

It avoids partial runs, active merges and live workers within four runs of their
end. After verified stage completion and stopped workers, it packs remaining
worker and merged locations; inode accounting avoids double-counting hardlinks.
Live SQLite WALs are skipped temporarily. Permanent failures are recorded and
retried only after relevant files change.

baseline_storage_status.json records completed/packed counts, archive bytes,
loose object counts, inode-deduplicated object/archive usage, disk free space and
remaining-storage projections. Projections show their actual sample policies,
scenarios and origins; a borrowed sample is explicitly labeled. They exclude
other stages, active partial runs, models, datasets and reports and are not
storage guarantees.

The default minimum free-space reserve is 2 GiB. If threatened, the watcher
reports the condition and stops itself, leaving other jobs running. Use --once
for a single pass, --interval for another polling interval, --end-guard for a
different finish margin, or --reserve-gib to increase the reserve.
