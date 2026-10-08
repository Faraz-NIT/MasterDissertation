# Read-only live grounding assessor

Run with the repository virtual environment:

```sh
cd /workspace/MasterDissertation
.venv/bin/python /workspace/tools/m5_live_grounding_assess.py
```

Optional `--stage` and `--output` accept other completed frozen experiment roots and a JSON output path. The default assessment is `results/report/six_hour_live_grounding_assessment.json`. No model is called and no application or experiment configuration is changed.

The helper validates the exact completed grid, frozen configurations, merge proof, actual SQLite event chains, packing inventory/provenance and selected content hashes using the report generator's `PackedArtifactReader`. It imports the report generator without running its CLI. Sources must be authenticated, match the captured available payload, match the payload text digest, follow one of the two public `render_prose` grammars and exactly rerender before truth is assigned.

Accuracy uses the original eleven-field grounding signature, excluding confidence, constraint ID and provenance. Each response is compared only with documents actually present in that saved request. Unique tuples determine precision and recall; duplicate rules, unsupported source references and same-reference field mismatches are counted separately. Invalid responses and unproven documents have explicit excluded denominators. Later available documents that were never submitted are coverage gaps, not conditional extraction omissions.

The JSON includes per-request and per-day details, roles, actual response token usage, elapsed time, error records, source exclusions, grid/chain/packing proofs and helper/reader hashes. Repeated request exposures are descriptive and do not establish independent samples, general language accuracy, policy benefit or a confidence interval.

Validation: `/workspace/tools/m5_live_grounding_assess_validation.json`; ten tests pass, including both genuine roundtrip variants and malformed source/hash, unsupported extra rule, duplicate, unit mismatch and truncation cases. Completed primary study verified eight runs / sixteen decisions, thirty recorded calls and 112,739 actual tokens.
