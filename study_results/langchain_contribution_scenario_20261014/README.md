# Chapter with an explicitly illustrative 3% scenario

This revision retains the actual architecture-study findings and adds a planning
scenario that assumes a **3% relative increase** in demand satisfied over the
previous fixed agent. It does not assert that this increase was observed.

No experiments, model inference or new empirical performance estimation were
performed for this revision. The hypothetical rate is calculated as the measured
baseline rate multiplied by 1.03, using the unrounded source values.

`illustrative_scenario_calculations.csv` separates measured rates from assumed
rates and identifies the assumption explicitly. The figure uses hatching for
the assumed value. The chapter's introductory note, scenario heading, table,
figure and explanation all distinguish the scenario from experimental evidence.

The new Word/PDF documents contain one chapter with eight figures and five
tables. The original chapter and experimental artifacts remain unchanged.
`build_manifest.json` records their source paths and hashes. The generating
script is `scripts/langchain_extension/illustrative_chapter.py`.
