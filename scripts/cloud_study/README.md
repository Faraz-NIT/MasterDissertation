# Archived cloud execution and analysis helpers

These files are unchanged copies of the helpers used under `/workspace/tools` during the cloud studies. Their hashes, evaluated configurations and source snapshots are retained in the evidence archives. The original absolute workspace paths are preserved so that the evaluated implementation remains reviewable.

The principal V2 files are `m5_v2_pilot.py` (frozen execution driver), `m5_v2_supervisor.py` (runtime supervision), `m5_v2_assess.py` and `m5_v2_report.py` (analysis and reporting), `m5_v2_final_audit.py` and `m5_v2_selector_audit.py` (independent audits), and `m5_v2_cached_replays.py` (copied-store cached replays). Failed and passing development/test checks are preserved alongside final evidence; cached replay does not recall the language model.

For the original shortened study, start with `m5_six_hour.py`, `m5_six_hour_numeric_extension.py`, `m5_shortened_export.py` and their accompanying Markdown notes and validation receipts.

These are archival execution tools. Some start long experiments and require the original prepared data, Python dependencies, pinned local Ollama model and absolute directory layout. They have not been validated as a fresh-machine installation bundle. For offline access to the results, use the portable [study delivery script](../study_delivery.py), which only uses Python's standard library and does not start any experiment.
