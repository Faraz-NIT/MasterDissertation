# Conclusion and future research: rewritten Chapter 7

Download the [chapter-only Word document](Conclusion_and_Future_Research_Rewritten.docx)
or [four-page PDF](Conclusion_and_Future_Research_Rewritten.pdf).
The [editable chapter](chapter_7.md) answers the main research question, RQ1–RQ4,
and hypotheses H1a, H1b, H2a, H2b, H3 and H4 from the
[revised literature review](../literature_review_20261013/chapter_2.md).

The chapter distinguishes improvement over conventional ordering from the LLM's
incremental contribution over the same planner. H1a and H1b are supported in both
simulated datasets; H2a and H2b are not supported. H3 is supported for the controlled
tasks. H4 remains exploratory because the original analysis did not perform a formal
cross-dataset effect test. Future research focuses on real messages, staff time,
promotion handling, longer horizons and an explicit test of context differences.

The document contains only Chapter 7 and uses Times New Roman, 12-point main text,
1.5 spacing, justified paragraphs and one-inch A4 margins. It is a standalone
replacement chapter for integration with the full dissertation.

## Verification and reproduction

[evidence_map.json](evidence_map.json) records the existing study sources and numerical
values used in the chapter. [build_manifest.json](build_manifest.json) records document
hashes and scope, and [validation.json](validation.json) records checks of completeness,
formatting, PDF bounds and the hypothesis table. The [contact sheet](review_contact_sheet.png)
and [full-size hypothesis review](hypothesis_table_review.png) document the visual review.

The revision uses the completed [clean Ollama study](../ollama_clean_study_20261009/).
No new experiment, model call or statistical effect test was performed.
With python-docx, PyMuPDF, Pillow and LibreOffice installed, run from the repository:

```bash
python study_results/conclusion_revision_20261013/build_document.py
soffice --headless --convert-to pdf --outdir study_results/conclusion_revision_20261013 study_results/conclusion_revision_20261013/Conclusion_and_Future_Research_Rewritten.docx
python study_results/conclusion_revision_20261013/verify_document.py
```

Rebuilding changes document metadata and file hashes; the text and checks use the
same recorded empirical evidence.
