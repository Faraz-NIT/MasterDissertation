# Verified M5 object packing

Use the repository virtualenv:

```bash
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_pack_artifacts.py --pack /absolute/registered/run
/workspace/MasterDissertation/.venv/bin/python /workspace/tools/m5_pack_artifacts.py --restore /absolute/registered/run
```

Both flags accept multiple run directories. Packing uses ZIP deflate level 6;
`--level 1` trades compression for speed. It uses one CPU process and launches no
experiments. Paths must be generated outputs registered in pipeline_status.json,
or their worker directories. Symlinks, tracked paths, incomplete runs, unknown
object files, uncheckpointed SQLite WALs and invalid chains are refused.

The archive contains every original object. Before deleting an object, the helper
verifies the archive entry against its original bytes, SHA-256, size and SHA
filename. It also requires every object to be reachable from the generated audit
events or trace indexes. packing_manifest.json records the original inventory,
archive hash, retained/archived partitions and recovery instructions. Matching
repeated operations are safe; conflicting existing files are never overwritten.

Only the first three trace objects and the certificate/proposal objects needed by
the standard HTML report remain unpacked. **Full traces and raw model calls are
archived and recoverable. Restore before full audit, replay, grounding analysis or
human-packet generation.** Restore to the current run location after merging; the
archive is portable within registered output roots.

Deleting one hardlink does not reclaim data held by another worker/merged path.
Pack before copying completed worker runs, or pack each existing linked location
once safe. Keep sufficient space for the compressed archive during packing and
the complete object inventory during restoration. The archive remains after
restoration and can be reused by a later pack.

Testing uses only copies under /tmp/m5_pack_test_* with an explicit fixture
provenance marker and --fixture-root. Actual experiment outputs are untouched by
fixture validation.
