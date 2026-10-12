# Complete rewritten dissertation: M5 and RetailNet

This is a full new dissertation built around the completed clean Ollama study. It uses
the supplied **GilbertMatteo-DMDSMastersThesis.pdf** for structural guidance: business
problem, data, model roles, research framework, findings, implications and conclusion.
The reference thesis is not redistributed and its wording, findings and figures are not copied.

## Downloads

- [Full editable Word dissertation](LLM_Agents_Replenishment_Dissertation.docx)
- [PDF dissertation](LLM_Agents_Replenishment_Dissertation.pdf)
- [Documents, all graphs, editable sources and validation ZIP](LLM_Agents_Dissertation_download.zip)
- [All 21 figures](figures/)

The PDF has **70 pages**, including **52 pages of main chapters**. Main prose contains
**15,751 words** (15,693 by whitespace counting), excluding front matter, headings,
tables, captions, references and appendices. The results chapter is 865 words and the
conclusion 590 words. The dissertation contains seven chapters, 21 clearly labelled
figures, ten explanatory tables and 26 references.

The Word document uses Times New Roman, 12-point body text, 1.5 line spacing,
one-inch margins and justified paragraphs. The cloud PDF renderer uses the installed
metric-compatible serif font. Contents and figure-list links are clickable, and saved
contents page numbers were checked against the final export. Rebuild page numbers
after making changes that alter pagination.

## Empirical scope and interpretation

The quantitative foundation is the [completed no-repair Ollama study](../ollama_clean_study_20261009/),
published in commit `4721351c3745fd51db9fa10b86b7e9d9839a821c`. It contains 30 selected
series per dataset, two weekly windows, three situations, 30 simulation seeds,
1,080 policy runs and 7,560 fresh model calls. Earlier repair and recovery outcomes
are not pooled into this dissertation.

Compared with conventional ordering, the complete workflow increased simulated
fulfilment by 25.28 percentage points in M5 and 0.78 points in RetailNet. The paired
inventory operating-cost reductions were 70.34% and 4.52%. Supplier reading was
accurate in the controlled message corpus. The same numerical planner without the
LLM performed almost identically in M5 and slightly better in RetailNet, so the
dissertation credits the numerical capability for most performance gains.

The language model was pretrained Qwen2.5 1.5B, served locally through Ollama on
Linux with four allocated CPU cores, 32 GiB memory and no GPU inference. It was not
trained or fine-tuned on either retail dataset. LightGBM was fitted locally to earlier
retail histories; there were four primary fits of one shared forecasting family.
The main methods chapter and appendix distinguish fitting from inference.

Inventories, suppliers, delivery events, cost coefficients and shelf life are simulated.
Recorded sales are a demand proxy; true latent demand is not recovered. Controlled
supplier texts, two historical weeks and selected panels limit transfer. The text does
not claim observed retailer profit, live purchasing, staff-time savings or participant findings.

## Sources and verification

- [Editable chapters](chapters/), [assembled manuscript](manuscript.md),
  [appendices](appendices.md) and [references](references.md).
- [Rewrite brief](rewrite_brief.json): exact structural reference and school requirements.
- [Figure register](figure_register.json): labels, inputs, image hashes and plotted priorities.
- [Build manifest](build_manifest.json): chapter counts, source hashes and format.
- [Validation receipt](validation_receipt.json): whole-text inclusion, independent headline
  recalculation, citation matching, exact embedded images, contents links and all-page bounds.
- [Visual review](visual_review_receipt.json): all-page contact-sheet and representative-page checks.
- [Delivery manifest](delivery_manifest.json): verified archive membership and bytes.
- [Git verification](git_verification.json): staged bytes compared with the delivered files.

The document ZIP is a reading and editing package. The [complete experiment ZIP](../ollama_clean_study_20261009/Fresh_Ollama_Study_download.zip)
separately contains the raw model calls, prepared data and full decisions. Reproduction
snapshots of the new document helpers are included; rebuilding uses the complete repository.

## Rebuild

With the existing document dependencies and completed study evidence:

```bash
python scripts/ollama_dissertation/figures.py
python scripts/ollama_dissertation/build.py
soffice -env:UserInstallation=file:///tmp/ollama-dissertation-office-20261012 --headless --convert-to pdf --outdir study_results/ollama_dissertation_20261012 study_results/ollama_dissertation_20261012/LLM_Agents_Replenishment_Dissertation.docx
python scripts/ollama_dissertation/validate.py --update-contents
python scripts/ollama_dissertation/build.py
soffice -env:UserInstallation=file:///tmp/ollama-dissertation-office-20261012 --headless --convert-to pdf --outdir study_results/ollama_dissertation_20261012 study_results/ollama_dissertation_20261012/LLM_Agents_Replenishment_Dissertation.docx
python scripts/ollama_dissertation/validate.py
python scripts/ollama_dissertation/package.py
```

The toolchain uses Python, python-docx, pandas, NumPy, matplotlib, PyMuPDF, Pillow,
lxml, Graphviz and LibreOffice. These commands read the completed evidence; they do
not train a language model or restart the replenishment experiment. Review new
rendered pages after editing; the current visual-review receipt covers this export.
