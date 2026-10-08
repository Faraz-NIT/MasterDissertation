# Rewritten M5 and RetailNet dissertation

This is the latest complete dissertation. It was rewritten around the structure and presentation
of the supplied Matteo Gilbert master's thesis, rather than expanded from the earlier version.
The reference thesis is not redistributed. The completed experiments and their original files
remain unchanged.

## Downloads

- [Full editable Word document](LLM_Replenishment_Business_Dissertation.docx)
- [PDF for reading](LLM_Replenishment_Business_Dissertation.pdf)
- [Documents, all 22 figures, sources and validation records](LLM_Replenishment_Dissertation_download.zip)

On GitHub, open a file and select **Download raw file**. These copies are held in the repository
and do not depend on the cloud computer remaining connected.

## Presentation and scope

The six chapters move from the retail problem and relevant research to the study design,
findings, business implications and conclusion. Results use short explanations alongside graphs.
The main prose contains **15,997 words** (15,948 by whitespace counting), excluding front matter,
headings, tables, figure captions, references and appendices. The PDF has **67 pages**, including
**51 pages of main chapters**. It contains 22 figures, eight tables and 26 references.

The Word document specifies Times New Roman, 12-point main text, 1.5 line spacing,
one-inch margins and justified body paragraphs. The cloud PDF renderer used the installed
Liberation Serif font as a metric-compatible substitute. Contents entries and figure-list links
are clickable, and the saved page numbers were checked against this PDF export. If the text or
layout changes, regenerate the contents page numbers using the commands below.

Graphs identify **M5**, **RetailNet**, or both in their titles and captions. M5 uses blue and
RetailNet green, with written labels so interpretation does not depend on colour. Captions
distinguish numerical-policy tests, matched language-model studies, the exploratory RetailNet
follow-up and separate simulated perishability calculations.

The study computer was Linux with four allocated CPU cores, 32 GiB memory and no GPU.
The local language model was pretrained **Qwen2.5 1.5B**, served through Ollama. It was not
trained or fine-tuned on either dataset. The numerical forecasting models were fitted to retail
histories; this distinction is explained in the methods chapter.

Verified inventory repair improved simulated cost and service in the tested fault scenario.
The capable rule-based reader achieved the same matched outcomes as the language model.
The dissertation therefore supports the controlled recovery workflow while identifying further
LLM-specific value as a question for future testing. It does not claim measured commercial ROI,
live deployment, or a language-model advantage that the experiments did not establish.

## Evidence and checks

- [Build manifest](build_manifest.json): word counts, source hashes and final document hashes.
- [Validation receipt](validation_receipt.json): formatting, contents links, numerical recalculation,
  reader comparisons, figure integrity and PDF layout checks.
- [Visual review receipt](visual_review_receipt.json): selected-page review in addition to automated
  checks of every PDF page.
- [Figure register](figure_register.json): plotted values, input file hashes, image hashes and captions.
- [Delivery manifest](delivery_manifest.json): exact delivered file and ZIP-member hashes.
- [Git staging verification](git_staging_verification.json): staged Git bytes checked before publication.
- [Original study reports and complete evidence](../README.md): detailed results and restoration tools.

The ZIP includes the documents, all figures, manuscript, appendices, references, production logs
and validation records present when packaged. The delivery manifest and subsequent Git staging
receipt sit beside the ZIP to avoid self-referential hashes. Source scripts are in the repository's
`scripts/` directory; they read completed evidence and do not run models or experiments.

## Rebuild from the repository

Use Python 3.11 or later with `python-docx`, `pandas`, `numpy`, `matplotlib`, `PyMuPDF`
and `lxml`, plus LibreOffice for PDF export. The figure and document builders depend on the
existing study results in the full repository; this download ZIP alone is a reading/editing package.

```bash
python scripts/build_business_figures.py
python scripts/build_business_dissertation.py
soffice -env:UserInstallation=file:///tmp/business-dissertation-office --headless --convert-to pdf --outdir study_results/business_dissertation study_results/business_dissertation/LLM_Replenishment_Business_Dissertation.docx
python scripts/validate_business_dissertation.py --update-contents
python scripts/build_business_dissertation.py
soffice -env:UserInstallation=file:///tmp/business-dissertation-office --headless --convert-to pdf --outdir study_results/business_dissertation study_results/business_dissertation/LLM_Replenishment_Business_Dissertation.docx
python scripts/validate_business_dissertation.py
python scripts/package_business_dissertation.py
```

The manuscript is editable in [manuscript.md](manuscript.md); appendix prose is in
[appendices.md](appendices.md). After changes, review the new rendered pages before publication.
The saved visual review receipt describes the current export, not every future rebuild.
