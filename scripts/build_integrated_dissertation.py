"""Integrate verified M5 evidence into the user-supplied Word dissertation.

The original document and experimental artifacts are read-only inputs.
python-docx is required. The output includes every completed run and all 25
scientific figures from the two final reports; no experiment is started.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import shutil
from zoneinfo import ZoneInfo

import pandas as pd
from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Inches, Pt, RGBColor
from docx.table import Table
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "study_results/dissertation"
SOURCE = ROOT / "study_results/research_context/Evidence_Gated_Autonomy_Dissertation_Revised.docx"
TARGET = OUT / "Evidence_Gated_Autonomy_Dissertation_Final.docx"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    document = Document(SOURCE)
    originals = [e for e in document.element.body if e.tag in {qn("w:p"), qn("w:tbl")}]
    styles = {s.name: s for s in document.styles}
    styles.update({s.style_id: s for s in document.styles})
    for name in ["Normal", "Body Text", "First Paragraph", "Compact", "Definition", "Definition Term"]:
        if name in styles:
            styles[name].font.name = "Times New Roman"
            styles[name].font.size = Pt(11.5)
            styles[name].paragraph_format.line_spacing = 1.3
            styles[name].paragraph_format.space_after = Pt(6)
    for name in ["Heading 1", "Heading 2", "Heading 3"]:
        if name not in styles:
            continue
        s = styles[name]
        s.font.name = "Times New Roman"
        s.font.color.rgb = RGBColor.from_string("173D43")
        s.font.size = Pt({"Heading 1": 17, "Heading 2": 13, "Heading 3": 12}[name])
        s.paragraph_format.keep_with_next = True
        s.paragraph_format.space_before = Pt(12)
        s.paragraph_format.space_after = Pt(7)
        if name == "Heading 1":
            s.paragraph_format.page_break_before = True
    for section in document.sections:
        section.page_width = Cm(21)
        section.page_height = Cm(29.7)
        section.top_margin = section.bottom_margin = Cm(2.4)
        section.left_margin = section.right_margin = Cm(2.5)
        section.header_distance = section.footer_distance = Cm(1.1)
    document.core_properties.title = Paragraph(originals[0], document).text
    document.core_properties.subject = "Completed M5 replenishment experiments, managerial findings and full evidence"
    document.core_properties.keywords = "M5; LLM agents; replenishment; evidence gating; recovery; business school"
    document.core_properties.comments = "Integrated from the supplied revised dissertation and verified experiment artifacts."
    document.core_properties.modified = datetime.now(ZoneInfo("UTC")).replace(tzinfo=None)
    update = OxmlElement("w:updateFields")
    update.set(qn("w:val"), "true")
    document.settings.element.append(update)
    footer = document.sections[0].footer.paragraphs[0]
    footer.clear()
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer.add_run("Page ")
    for instruction in ["PAGE", "NUMPAGES"]:
        field = OxmlElement("w:fldSimple")
        field.set(qn("w:instr"), instruction)
        footer._p.append(field)
        if instruction == "PAGE":
            footer.add_run(" of ")
    for run in footer.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(9)
    header = document.sections[0].header.paragraphs[0]
    header.text = "Evidence-Gated Autonomy for Retail Replenishment"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(9)

    v1 = pd.read_csv(ROOT / "study_results/v1/M5_six_hour_results.csv")
    v2 = pd.read_csv(ROOT / "study_results/v2/M5_v2_results.csv")
    numeric = v1[v1.comparison_group == "numerical_7_days"]
    initial = json.loads((ROOT / "study_results/v1/M5_six_hour_study_report_data.json").read_text())
    assessment = json.loads((ROOT / "study_results/v2/M5_v2_independent_assessment.json").read_text())
    protocol = json.loads((ROOT / "results/v2_pilot/protocol.json").read_text())
    assert len(v1) == 372 and len(numeric) == 360 and len(v2) == 32
    assert int(v1.trace_count.sum()) == 2544 and int(v2.trace_count.sum()) == 448
    assert int(v2.hard_violations.sum()) == 0
    group2 = v2.groupby(["arm", "scenario"])
    means2 = group2[["cost", "fill_rate"]].mean()
    for recovery in ["no_recovery", "recovery"]:
        for scenario in v2.scenario.unique():
            assert means2.loc[("llm_v2_" + recovery, scenario)].equals(
                means2.loc[("parser_" + recovery, scenario)]
            )
    collapse_before = means2.loc[("llm_v2_no_recovery", "derived_field_collapse")]
    collapse_after = means2.loc[("llm_v2_recovery", "derived_field_collapse")]
    assert round(100 * (collapse_after.cost / collapse_before.cost - 1), 2) == -10.93
    assert round(100 * (collapse_after.fill_rate - collapse_before.fill_rate), 2) == 7.0
    arm_names = {
        "parser_no_recovery": "P0", "parser_recovery": "P1",
        "llm_v2_no_recovery": "L0", "llm_v2_recovery": "L1",
    }
    scenario_names = {
        "normal": "Normal", "derived_field_collapse": "Derived-field collapse",
        "feed_gap": "Feed gap", "capacity_cut": "Capacity cut",
    }
    used_figures = []
    generated_tables = []
    figure_number = 0

    def paragraph(text, style="Body Text", size=None):
        p = document.add_paragraph(style=styles.get(style, styles["Normal"]))
        parts = re.split(r"(\*\*[^*]+\*\*)", text)
        for part in parts:
            if not part:
                continue
            run = p.add_run(part[2:-2] if part.startswith("**") else part)
            if part.startswith("**"):
                run.bold = True
            if size:
                run.font.size = Pt(size)
        return p._p

    def heading(text, level=2):
        return paragraph(text, "Heading " + str(level))

    def table(caption, columns, rows, widths=None, size=9):
        caption_element = paragraph(caption, size=10)
        Paragraph(caption_element, document).paragraph_format.keep_with_next = True
        elements = [caption_element]
        t = document.add_table(rows=1, cols=len(columns))
        for cell, value in zip(t.rows[0].cells, columns):
            cell.text = str(value)
        for row in rows:
            for cell, value in zip(t.add_row().cells, row):
                cell.text = str(value)
        if widths:
            t.autofit = False
            for col, width in zip(t.columns, widths):
                for cell in col.cells:
                    cell.width = Cm(width)
        for index, row in enumerate(t.rows):
            no_split = OxmlElement("w:cantSplit")
            row._tr.get_or_add_trPr().append(no_split)
            for cell in row.cells:
                for p in cell.paragraphs:
                    p.paragraph_format.line_spacing = 1.05
                    p.paragraph_format.space_after = Pt(4)
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.keep_with_next = index == 0
                    for run in p.runs:
                        run.font.name = "Times New Roman"
                        run.font.size = Pt(size)
                        run.bold = index == 0
                if index == 0:
                    shading = OxmlElement("w:shd")
                    shading.set(qn("w:fill"), "E4ECEB")
                    cell._tc.get_or_add_tcPr().append(shading)
        repeat = OxmlElement("w:tblHeader")
        t.rows[0]._tr.get_or_add_trPr().append(repeat)
        elements.append(t._tbl)
        generated_tables.append({"caption": caption, "rows": len(rows), "columns": columns})
        return elements

    def fig(path, caption, number):
        p = document.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next = True
        p.add_run().add_picture(str(path), width=Inches(6.15))
        used_figures.append({"number": number, "path": str(path.relative_to(ROOT)), "sha256": sha(path), "caption": caption})
        return [p._p, paragraph("Figure " + number + ". " + caption, size=10)]

    figures = {
        "v1_numeric_cost": ("v1/M5_six_hour_study_report_six_hour_numeric_30seeds_cost_service.png",
            "Initial numerical study: cost and service across the three scenarios. Thirty seeds per policy/scenario; seven days; structured rules. These are simulated trade-offs, not LLM outcomes."),
        "v1_numeric_safety": ("v1/M5_six_hour_study_report_six_hour_numeric_30seeds_violations_holds.png",
            "Initial numerical study: hard violations and held decisions. Holds and violations are different endpoints; reference deviations are reported separately."),
        "v1_grounding_quality": ("v1/M5_six_hour_study_report_live_grounding_quality_coverage.png",
            "Initial live-model grounding: conditional tuple accuracy and document coverage. Accuracy is measured on submitted rules; unprocessed sources do not count as successful extraction."),
        "v2_normal_cost": ("v2/M5_v2_cost_service_normal.png",
            "V2 normal operation: cost and fill by configuration. Each configuration has two seeds and fourteen days. The LLM and parser means are identical."),
        "v2_collapse_cost": ("v2/M5_v2_cost_service_derived_field_collapse.png",
            "V2 derived-field collapse: verified recovery restores cost and service in both parser and LLM configurations. The improvement is attributable to recovery."),
        "v2_capacity_cost": ("v2/M5_v2_cost_service_capacity_cut.png",
            "V2 supplier capacity cut: all configurations respect the active constraints. The LLM supplies a checked numeric term, not the final order quantity."),
        "v2_collapse_latency": ("v2/M5_v2_inventory_latency_derived_field_collapse.png",
            "V2 derived-field collapse: inventory and decision latency. Service recovery and inference effort should be assessed together; local execution has no priced hosting estimate."),
        "v2_execution_safety": ("v2/M5_v2_execution_safety.png",
            "V2 execution and safety: nonzero replenishment, holds and committed-plan violations. Zero committed violations does not imply zero semantic model errors."),
    }

    def dynamic_table(key):
        if key == "study_scope":
            rows = [
                ["Initial numerical", "B1–B4", "30", "7", "3", "360 / 2,520"],
                ["Initial prose feasibility", "B3, B4, B9, B10", "1", "2", "2", "8 / 16"],
                ["Structured controls", "B3, B4", "1", "2", "2", "4 / 8"],
                ["V2 matched pilot", "P0, P1, L0, L1", "2", "14", "4", "32 / 448"],
            ]
            return table("Table 5.2a. Completed scope; every row uses thirty series and one decision origin.",
                         ["Stage", "Policies / arms", "Seeds", "Days", "Scenarios", "Runs / traces"], rows)
        if key == "trace_framework":
            original = Table(originals[227], document)
            statuses = ["Input/hash audit", "Input/hash audit", "Bounded source audit only", "Bounded source audit only",
                        "No full rationale comparison", "Five selected cached replays", "Two numerical interventions",
                        "Structural forecast removal only", "No dedicated prompt replication test", "Not conducted"]
            rows = [row + [status] for row, status in zip([[c.text for c in row.cells] for row in original.rows[1:]], statuses)]
            return table("Table 5.3. Trace evaluation framework and completed coverage.",
                         ["Metric", "Planned operational definition", "Completed evidence"], rows)
        if key == "v1_means":
            g = numeric.groupby(["policy", "scenario"])
            rows = []
            for (policy, scenario), frame in g:
                rows.append([policy, scenario_names[scenario], f"{frame.cost.mean():.2f}",
                    f"{100 * frame.fill_rate.mean():.2f}", f"{frame.bullwhip.mean():.2f}",
                    str(int(frame.held_decisions.sum())), str(int(frame.hard_violations.sum()))])
            return table("Table 6.1. Initial numerical benchmark. Means across thirty seeds; total holds and violations across each 210-decision cell.",
                         ["Policy", "Scenario", "Cost USD", "Fill %", "Bullwhip", "Holds", "Hard violations"], rows)
        if key == "v2_means":
            rows = []
            for (arm, scenario), frame in group2:
                rows.append([arm_names[arm], scenario_names[scenario], f"{frame.cost.mean():.2f}",
                    f"{100 * frame.fill_rate.mean():.2f}", str(int(frame.held_decisions.sum())),
                    str(int(frame.hard_violations.sum()))])
            return table("Table 6.2. V2 matched outcomes. P0/P1: parser without/with recovery; L0/L1: LLM without/with recovery. Means across two seeds; holds and violations summed over 28 decision days per row.",
                         ["Arm", "Scenario", "Cost USD", "Fill %", "Holds", "Hard violations"], rows)
        if key == "recovery_contrast":
            before = group2.get_group(("llm_v2_no_recovery", "derived_field_collapse"))
            after = group2.get_group(("llm_v2_recovery", "derived_field_collapse"))
            rows = []
            for label, field, factor in [("Mean portfolio cost, USD", "cost", 1), ("Fill rate, %", "fill_rate", 100),
                    ("Stockout frequency, %", "stockout_rate", 100), ("Mean aggregate stock, units", "mean_inventory", 1),
                    ("Mean bullwhip diagnostic", "bullwhip", 1)]:
                a, b = before[field].mean() * factor, after[field].mean() * factor
                rows.append([label, f"{a:.2f}", f"{b:.2f}", f"{b-a:+.2f}"])
            rows.append(["Held decision days (total)", str(int(before.held_decisions.sum())), str(int(after.held_decisions.sum())), "-10"])
            return table("Table 6.3. Derived-field recovery effect. Parser and LLM configurations have identical values; cost falls 10.93% and fill improves seven percentage points.",
                         ["Measure", "No recovery", "Recovery", "Change"], rows)
        if key == "grounding_summary":
            rows = [
                ["Initial full-tuple model task", "30 total calls", "88 exact / 95 returned / 112 submitted", "92.63% precision; 78.57% recall", "7 unit errors; 24 omitted submitted rules"],
                ["V2 compact model extraction", "48 fresh extraction calls", "76 exact / 76 submitted numeric terms", "100% on this bounded target", "0 false or omitted submitted terms"],
                ["V2 eligible pipeline sets", "388 eligible days, all arms", "157 rules per eligible day", "100% active-set coverage", "60 state-gated days excluded"],
                ["V2 model recovery selection", "20 fresh selections", "10 instruction-compliant choices", "50% instruction compliance", "10 stale-feed errors blocked"],
            ]
            return table("Table 6.4. Grounding and selection outcomes. Targets and denominators differ; the rows are not a common accuracy benchmark.",
                         ["Task", "Exposure", "Exactness", "Conditional result", "Failures / boundary"], rows, size=8.5)
        if key == "cost_components":
            components = ["purchase", "fixed_order", "transfer", "holding", "shortage", "spoilage"]
            component_means = []
            for arm in ["llm_v2_no_recovery", "llm_v2_recovery"]:
                records = [pd.read_csv(path)[components + ["cost"]].sum()
                           for path in sorted((ROOT / "results/v2_pilot" / arm).glob("B10__derived_field_collapse__*/daily.csv"))]
                assert len(records) == 2
                means = pd.DataFrame(records).mean()
                assert abs(means[components].sum() - means["cost"]) < 0.000001
                component_means.append(means)
            rows = []
            labels = {"purchase": "Purchase", "fixed_order": "Fixed order", "transfer": "Transfer",
                      "holding": "Holding", "shortage": "Shortage penalty", "spoilage": "Spoilage", "cost": "Total"}
            for key_name in components + ["cost"]:
                before, after = [x[key_name] for x in component_means]
                rows.append([labels[key_name], f"{before:.2f}", f"{after:.2f}", f"{after-before:+.2f}"])
            return table("Table 6.3a. Collapse-scenario cost components, simulated USD. Means across two fourteen-day runs in each LLM configuration; the parser cost/service outcomes match. Rounded components may differ by one cent from the rounded total.",
                         ["Component", "No recovery", "Recovery", "Change"], rows)
        if key == "agent_runtime":
            rows = []
            for arm, frame in v2.groupby("arm"):
                rows.append([arm_names[arm], len(frame), int(frame.trace_count.sum()),
                    int(frame.llm_calls.sum()), f"{int(frame.tokens.sum()):,}", int(frame.held_decisions.sum())])
            return table("Table 6.5. V2 operating footprint by configuration. Eight runs and 112 decision days per configuration; parser arms have no LLM calls.",
                         ["Arm", "Runs", "Days", "Fresh calls", "Tokens", "Holds"], rows)
        if key == "replay_summary":
            rows = [
                ["P0 / collapse", "Held", "Yes", "Not applicable"],
                ["P1 / collapse", "Executed", "Yes", "Blocked reconstruction"],
                ["L0 / normal", "Executed", "Yes", "Blocked reconstruction"],
                ["L1 / collapse", "Executed", "Yes", "Blocked reconstruction"],
                ["L1 / feed gap", "Held", "Yes", "Not applicable"],
            ]
            return table("Table 6.6. Selected copied-store cached replays. No fresh model calls; original evidence stores remained unchanged.",
                         ["Configuration / scenario", "Original result", "State and action match", "Forecast removal"], rows)
        if key == "managerial_value":
            rows = [
                ["Source-backed numeric interpretation", "76/76 submitted terms exact; numerical workflow preserved", "Useful for bounded supported terms", "Natural document breadth and maintenance savings"],
                ["Evidence recovery", "Lower cost and higher fill in both parser and LLM arms", "Build source/ledger recovery before adding autonomy", "Long-run economics and field incident coverage"],
                ["Exception tool requests", "10/20 compliant; wrong requests blocked", "Keep deterministic eligibility and approval", "Reliable resolution of ambiguous cases"],
                ["Trace and review", "Integrity audit and five matching replays", "Provide verifiable evidence to reviewers", "Human review time, accuracy and workload"],
                ["Commercial language flexibility", "Parser matched the controlled-corpus outcomes", "Use a strong parser as the comparator", "Incremental benefit on heterogeneous contracts"],
            ]
            return table("Table 6.7. A conditional business case for LLM-assisted replenishment.",
                         ["Value proposition", "Observed evidence", "Management decision", "Still to establish"], rows)
        if key == "research_questions":
            rows = [
                ["RQ1", "V1 numerical benchmark; V2 matched costs/service", "LLM matches the strongest parser in the pilot", "Long-run/multi-origin and field comparisons"],
                ["RQ2", "63 versus 0 feed-gap violations in V1; V2 recovery benefit", "Evidence controls and verified recovery matter", "Broader faults and incremental LLM triage benefit"],
                ["RQ3", "Full-tuple failures; 76 exact compact numeric terms", "Bounded extraction is feasible with independent checking", "Natural contracts, coupled semantics and units"],
                ["RQ4", "Parser/LLM and recovery factorial comparisons", "Recovery benefit separated from model presence", "Role, critic, memory and free-form ablations"],
                ["RQ5", "Zero V2 committed violations; 10 selection errors", "The boundary contains mistakes; the model is not error-free", "Powered reliability and adversarial testing"],
                ["RQ6", "Integrity audit; five matching cached replays", "Selected recorded decisions are reproducible", "Semantic deletion and free-form comparison"],
                ["RQ7", "Software records only; no participants", "Human audit benefit remains unmeasured", "Approved planner study with review outcomes"],
            ]
            return table("Table 6.8. Answers to the retained research questions.",
                         ["Question", "Completed evidence", "Current answer", "Remaining evidence"], rows)
        if key == "hypotheses":
            rows = [
                ["H1", "Not fully tested", "No LLM-only comparator; closeness to numerical tools shown within V2"],
                ["H2", "Not tested", "No matched critic-removal comparison"],
                ["H3", "Not isolated", "V1/V2 target and tool changes prevent attribution solely to typed state"],
                ["H4", "Partial mechanism evidence", "Deterministic gating reduced violations; extra LLM evidence reasoning benefit unmeasured"],
                ["H5", "Bounded descriptive evidence", "Large tuple task failed; compact explicit terms succeeded; ambiguity not validated"],
                ["H6", "Partial mechanism evidence", "Selected replay/sensitivity passed; no free-form trace comparison"],
                ["H7", "Not tested", "No human participant audit"],
                ["H8", "Not fully tested", "Limited disturbances and horizons; no complete severe-shock/unrestricted comparison"],
            ]
            return table("Table 6.9. Status of H1–H8. No row constitutes a confirmatory significance claim.",
                         ["Hypothesis", "Status", "Reason"], rows)
        raise ValueError(key)

    def render(text):
        nonlocal figure_number
        result = []
        for block in re.split(r"\n\s*\n", text.strip()):
            block = block.strip()
            if not block:
                continue
            match = re.fullmatch(r"\[\[TABLE:(\w+)\]\]", block)
            if match:
                result.extend(dynamic_table(match.group(1)))
                continue
            match = re.fullmatch(r"\[\[FIGURE:(\w+)\]\]", block)
            if match:
                figure_number += 1
                path, caption = figures[match.group(1)]
                result.extend(fig(ROOT / "study_results" / path, caption, f"6.{figure_number}"))
                continue
            match = re.match(r"^(#{1,3}) (.+)$", block)
            if match:
                result.append(heading(match.group(2), len(match.group(1))))
            else:
                result.append(paragraph(" ".join(block.splitlines())))
        return result

    def boundary(index):
        p = Paragraph(originals[index], document)
        level = int(p.style.name.rsplit(" ", 1)[-1])
        for candidate in range(index + 1, len(originals)):
            element = originals[candidate]
            if element.tag == qn("w:p"):
                other = Paragraph(element, document)
                if other.style.name.startswith("Heading ") and int(other.style.name.rsplit(" ", 1)[-1]) <= level:
                    return candidate
        return len(originals)

    revisions = (OUT / "dissertation_revisions.md").read_text()
    entries = re.split(r"(?m)^@@ (paragraph|heading|replace|append|front)(?: (\d+))?\n", revisions)
    edits = [(entries[i], int(entries[i+1]) if entries[i+1] else None, entries[i+2].strip()) for i in range(1, len(entries), 3)]
    for operation, index, body in edits:
        if operation in {"paragraph", "heading"}:
            Paragraph(originals[index], document).text = body
    # Update the positioning table while preserving all its other source cells.
    Table(originals[89], document).rows[-1].cells[-1].text = "Bounded simulation evidence; field, role-ablation and human-audit claims remain open"
    problem = Paragraph(originals[133], document)
    problem.text = problem.text.replace(
        "minimize expected purchase + holding + shortage + transfer + expedite cost\n           + lambda * CVaR_alpha(total cost)",
        "minimize expected purchase + fixed order + holding + shortage\n           + transfer + spoilage cost + lambda * CVaR_alpha(total cost)",
    )
    for operation, index, body in edits:
        if operation not in {"replace", "append", "front"}:
            continue
        if operation == "front":
            anchor = originals[18]
        else:
            end = boundary(index)
            anchor = originals[end] if end < len(originals) else document.element.body[-1]
            if operation == "replace":
                for element in originals[index+1:end]:
                    if element.getparent() is not None:
                        element.getparent().remove(element)
        for element in render(body):
            anchor.addprevious(element)

    # The contents page includes the major chapters and front matter. Word can
    # update the field on opening; the PDF render pass supplies cached pages.
    contents_heading = paragraph("Contents", "Title")
    Paragraph(contents_heading, document).paragraph_format.page_break_before = True
    originals[18].addprevious(contents_heading)
    toc = document.add_paragraph()
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), 'TOC \\o "1-1" \\h \\z \\u')
    field.set(qn("w:dirty"), "true")
    toc._p.append(field)
    originals[18].addprevious(toc._p)
    artifact_refs = [
        "M5 replenishment agent version-2 pilot [Simulation report, run tables and evidence]. (2026). MasterDissertation experiment repository. https://github.com/Faraz-NIT/MasterDissertation/blob/main/study_results/v2/M5_v2_pilot_report.md",
        "Six-hour M5 study: Final snapshot [Simulation report, run tables and evidence]. (2026). MasterDissertation experiment repository. https://github.com/Faraz-NIT/MasterDissertation/blob/main/study_results/v1/M5_six_hour_study_report.md",
    ]
    for text in artifact_refs:
        originals[346].addprevious(paragraph(text))

    # Original tables keep their contents; style them consistently and repeat headers.
    for element in document.element.body:
        if element.tag == qn("w:tbl"):
            t = Table(element, document)
            for row in t.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        p.paragraph_format.line_spacing = 1.05
                        p.paragraph_format.space_after = Pt(4)
                        for run in p.runs:
                            run.font.name = "Times New Roman"
                            run.font.size = Pt(9)
            if t.rows and t.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is None:
                t.rows[0]._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))

    def append_elements(elements):
        for element in elements:
            document.element.body[-1].addprevious(element)

    landscape = document.add_section(WD_SECTION_START.NEW_PAGE)
    landscape.page_width, landscape.page_height = Cm(29.7), Cm(21)
    landscape.orientation = 1
    append_elements([heading("Appendix B: Complete Run Results and Forecast Scores", 1),
        paragraph("Every completed run is included below. The numerical, two-day prose, structured-control and V2 grids remain separate. Costs are simulated USD; fill and stockouts are percentages; stock is mean aggregate on-hand units; turns are for the decision window. Holds and hard violations are counts. Ref. dev. is a clean-reference action deviation, not necessarily a constraint violation. No inference is made by pooling these rows.")])
    columns = ["Seed", "Cost USD", "Fill %", "Stockout %", "Mean stock", "Bullwhip", "Turns", "Holds", "Hard viol.", "Ref. dev."]
    def run_rows(frame):
        return [[int(row.seed), f"{row.cost:.3f}", f"{row.fill_rate*100:.3f}",
                 f"{row.stockout_rate*100:.3f}", f"{row.mean_inventory:.3f}", f"{row.bullwhip:.3f}",
                 f"{row.inventory_turns_window:.3f}", int(row.held_decisions),
                 int(row.hard_violations), int(row.reference_deviations)]
                for row in frame.sort_values("seed").itertuples()]
    counter = 0
    for (policy, scenario), frame in numeric.groupby(["policy", "scenario"]):
        counter += 1
        append_elements(table(f"Table B.{counter}. Initial numerical study: {policy}, {scenario_names[scenario]}; thirty seeds, seven days.", columns, run_rows(frame), size=9))
    for group in ["prose_feasibility_2_days", "structured_reference_2_days"]:
        frame = v1[v1.comparison_group == group]
        label = "Prose feasibility" if group.startswith("prose") else "Structured-rule controls"
        counter += 1
        extra_rows = []
        for (policy, scenario), case in frame.groupby(["policy", "scenario"]):
            for row in run_rows(case):
                extra_rows.append([policy, scenario_names[scenario]] + row)
        qualification = " All decisions were held." if group.startswith("prose") else ""
        append_elements(table(f"Table B.{counter}. {label}; two-day window, seed zero.{qualification}", ["Policy", "Scenario"] + columns, extra_rows, size=8))
    for arm, frame in v2.groupby("arm"):
        counter += 1
        extra_rows = []
        for scenario, case in frame.groupby("scenario"):
            for row in run_rows(case):
                extra_rows.append([scenario_names[scenario]] + row)
        append_elements(table(f"Table B.{counter}. V2 {arm_names[arm]} ({arm}); two seeds, fourteen days.", ["Scenario"] + columns, extra_rows, size=8.5))
    counter += 1
    scores = initial["forecast_backtests"]
    rows = [[{"deep": "Native GRU/NB"}.get(x["model"], x["model"]), x["origin"],
             "Pre-study holdout" if "holdout" in x["evaluation_role"] else "Overlapping descriptive",
             f"{x['wrmsse']:.5f}", f"{x['weighted_scaled_pinball']:.5f}", f"{x['crps']:.5f}",
             f"{x['coverage_95']*100:.3f}"] for x in scores]
    append_elements(table(f"Table B.{counter}. All sixteen recorded forecast backtest cases; thirty bottom series and 112 aggregate nodes. Lower error scores are better; coverage is reported against a 95% interval target.",
                          ["Model", "Origin index", "Role", "WRMSSE", "Weighted pinball", "CRPS", "Coverage %"], rows))

    portrait = document.add_section(WD_SECTION_START.NEW_PAGE)
    portrait.page_width, portrait.page_height = Cm(21), Cm(29.7)
    portrait.orientation = 0
    append_elements([heading("Appendix C: Complete Scientific Graph Collection", 1),
        paragraph("The two final reports contain twenty-five scientific graphs: sixteen from the initial shortened study and nine from V2. Eight have already been discussed in Chapter 6; the remaining seventeen appear here. Original image bytes and axes are preserved. Development timings, first-eight-seed summaries and final thirty-seed results retain their different exposures. These figures do not provide additional independent experiments.")])
    already = {x["path"] for x in used_figures}
    graph_paths = sorted((ROOT / "study_results/v1").glob("M5_six_hour_study_report*.png")) + sorted((ROOT / "study_results/v2").glob("*.png"))
    descriptions = {
        "execution_progress": "Initial study completion by stage. Completed controls are not language-model runs; merged and worker copies are counted once.",
        "grounding_latency": "Development extraction timings for the candidate model profiles. Receiving a response does not establish extraction accuracy or policy benefit.",
        "forecast_backtests": "Forecast scores using the preferred pre-study holdout origins where available. Separate origins and models are descriptive; no confidence interval is implied.",
        "six_hour_numeric_outcomes": "Initial eight-seed numerical phase only. These 96 runs are a subset of the later verified 360-run union, not additional observations to pool.",
        "six_hour_numeric_30seeds_deviations_execution": "Thirty-seed numerical benchmark: clean-reference deviations and execution. Reference deviation is not the same as an actual hard violation.",
        "six_hour_agentic_prose_cost_service": "Two-day controlled-prose feasibility: all decisions were held. Initial stock served demand; low purchase cost is not an LLM saving.",
        "six_hour_agentic_prose_violations_holds": "Two-day controlled-prose feasibility: violations and holds. A zero violation count in all-held cases does not demonstrate executable replenishment.",
        "six_hour_agentic_prose_deviations_execution": "Two-day controlled-prose feasibility: reference deviations and execution. No live-model proposal reached the optimizer.",
        "six_hour_agentic_prose_outcomes": "Two-day controlled-prose feasibility summary. The horizon and document carrier differ from the numerical and V2 comparisons.",
        "six_hour_structured_controls_cost_service": "Two-day structured-rule controls: cost and service. Orders create expenditure for future stock, without a terminal salvage credit.",
        "six_hour_structured_controls_violations_holds": "Two-day structured-rule controls: hard violations and holds. These are deterministic controls, not model-generated decisions.",
        "six_hour_structured_controls_deviations_execution": "Two-day structured-rule controls: reference deviations and execution.",
        "six_hour_structured_controls_outcomes": "Two-day structured-rule control summary; one seed and two scenarios.",
        "M5_v2_cost_service_feed_gap": "V2 stale-feed cost and service. Recovery cannot repair absent current evidence; all parser/LLM matched outcomes remain identical.",
        "M5_v2_inventory_latency_normal": "V2 normal-operation inventory and latency. A language interface adds inference work without a measured operating advantage on this corpus.",
        "M5_v2_inventory_latency_feed_gap": "V2 stale-feed inventory and latency. Held days must be assessed alongside service loss and review needs.",
        "M5_v2_inventory_latency_capacity_cut": "V2 capacity-cut inventory and latency. Changed constraints are checked before numerical planning.",
    }
    appendix_counter = 0
    for path in graph_paths:
        if str(path.relative_to(ROOT)) in already:
            continue
        appendix_counter += 1
        key = path.stem.replace("M5_six_hour_study_report_", "")
        caption = descriptions.get(key)
        if not caption:
            raise ValueError(f"Uncaptioned graph: {path}")
        append_elements(fig(path, caption, f"C.{appendix_counter}"))
    assert len(used_figures) == 25 and appendix_counter == 17

    append_elements([heading("Appendix D: Configuration, Development and Evidence Record", 1),
        heading("D.1 Implemented configuration and information boundaries", 2),
        paragraph("The settings below describe the evaluated V2 pilot, not a production service. The same saved forecaster, source inventory observations, numerical tools, gates and deterministic critic were used in every matched configuration. Clean simulator state and post-decision true-problem objects were used for assessment after decisions and were not supplied to the model.")])
    config = json.loads((ROOT / "results/v2_pilot/configs/llm_v2_no_recovery.json").read_text())
    appendix_config = [
        ["Portfolio", "Three selected FOODS items × ten stores = thirty series"],
        ["Decision origin and window", "Start index 1858; 1–14 March 2016; fourteen days"],
        ["Simulation seeds / scenarios", "13 and 29; normal, derived-field collapse, feed gap, capacity cut"],
        ["Warm-up and training", "Fourteen-day warm-up; last training date 15 February 2016"],
        ["Local language model", "Qwen2.5 1.5B, Q4_K_M, Ollama-compatible local endpoint"],
        ["Serving profile", "8,192-token context; temperature 0; model seed 42; three inference threads"],
        ["Model digest", protocol["selected_model"]["digest"]],
        ["Model task", "source_ref, value, unit, value_quote; supplier capacity and portfolio budget"],
        ["Forecast", "Saved native GRU/NB; lookback 56; hidden size 32; ten epochs; max 12,000 windows"],
        ["Forecast SHA-256", sha(ROOT / "results/v2_pilot/shared/model_deep_origin0.pt")],
        ["Optimizer", "Seven-day horizon; four scenarios; five-second time limit; MIP gap 0.001"],
        ["Risk / budget", "Risk weight 0.1; CVaR alpha 0.95; budget USD 3,000"],
        ["Inventory and transfers", "Order upper bound 1,000 units; eligible transfers enabled; storage 10,000 units per location"],
        ["Registered unit penalties", "Holding rate 0.015; shortage multiplier 5; transfer unit cost 0.3"],
        ["Gate controls", "Min quality 0.7; full quality 0.95; min confidence 0.9; feed age ≤1 day; max spend USD 1,500"],
        ["Other gate controls", "Hold budget 2; max days supply 45; max dispersion 4; two-person spend USD 2,500"],
        ["Approval / model failure", "Approval mode hold; on_failure hold; no real human approval or ERP execution"],
        ["Excluded LLM roles", "No LLM critic, no numerical routing by the LLM, no actionable memory"],
        ["Cache and correction", "Source-version-bound verified cache; at most one semantic correction; none needed in final extraction"],
    ]
    append_elements(table("Table D.1. Registered V2 settings and model identities.", ["Item", "Evaluated setting"], appendix_config, size=8.5))
    append_elements([heading("D.2 Development history and attribution", 2),
        paragraph("The first study selected a local Qwen2.5 1.5B model under the six-hour CPU constraint after earlier development exposed weaknesses in smaller or alternative profiles. Its full-tuple extraction failures remained in the final report. V2 development subsequently tested both Qwen 1.5B and Llama 3B: both failed the larger tuple head in the first round, while the reduced numeric head passed two of two development cases per model in the second round. Qwen was selected before the revised evaluation. These small development cases are not additional independent evidence of general model accuracy."),
        paragraph("The first ninety-six numerical runs used seeds 0–7. The extension added seeds 8–29 after the base results were available. Data, forecast-training tensors, LightGBM trees and numerical settings were checked before forming the nonduplicated 360-run view. Earlier long studies, paused checkpoints and superseded reports remain available as history; they are excluded from the 404 completed runs tabulated here."),
        paragraph("V2 changes included compact grounded terms, trusted metadata binding, a capable parser comparator, verified cache reuse, an independent recovery tool, a pre-HTTP request log and consistent unknown-arrival opportunity sampling. Multiple changes and a new historical window separate the stages. Their effects cannot be individually inferred from a before/after model comparison.")])
    append_elements([heading("D.3 Audit, software checks and reproducibility", 2),
        paragraph("The completed V2 audit checked 32 run identities, 448 decision traces, 68 fresh physical calls, 130,430 original content-addressed objects and 130,542 SQLite chain events. It also checked the 88-record workflow chain, 54 evaluated source/test pins, six prepared-data pins, two execution-helper pins and the identity of the shared forecaster. All completed source-rule sets and both recovery configurations were independently assessed. The software suite passed 218 tests, with one optional Anthropic integration test skipped because its SDK was unavailable."),
        paragraph("Fresh model requests were captured before transport and paired with their exact response or error. Requests, cache imports and later evaluation artifacts were counted separately. The audit checked the recorded context for forbidden evaluator keys and exact submitted-source equality. Zero client errors does not mean zero semantic errors: ten recovery choices were instruction-inconsistent and were blocked by the independent tool."),
        paragraph("The selected cached replay checks were performed on copied stores. Three executed and two held cases reproduced their recorded hashes; three forecast removals blocked reconstruction; and both large numerical counterfactuals changed the selected action without a new violation. These tests did not recall the model, inspect its internal reasoning or assess human understanding."),
        paragraph("The complete Git delivery preserves 199,102 pre-publication study files, including development failures, all original SQLite histories, raw evidence objects, compact exports, earlier studies and prepared panels. Every original path was restored and SHA-256 verified before publication. Archive parts avoid GitHub's individual-file size limit. Full raw M5 competition downloads, model weights, installed runtimes and credentials are excluded. Fresh-machine rerunning requires those dependencies and the original path-aware helpers; restoration alone does not start an experiment.")])
    evidence_rows = [
        ["Supplied revised Word dissertation", sha(SOURCE)],
        ["Original six-hour final PDF", sha(ROOT / "study_results/v1/M5_six_hour_study_report.pdf")],
        ["Original V2 final PDF", sha(ROOT / "study_results/v2/M5_v2_pilot_report.pdf")],
        ["V2 frozen protocol", sha(ROOT / "results/v2_pilot/protocol.json")],
        ["Original complete V2 evidence ZIP", "1095db66afb2d34d059b9d702a670e21f433f7c22773407a4797277312606234"],
        ["Published study implementation", "9b8e6c80344ab38f2c4f2b7cdf71eec6a0ea381f"],
        ["Publication receipt commit", "0d281178d6f67f27b68d90d25b0b3d145cc2c24c"],
    ]
    append_elements(table("Table D.2. Input and publication provenance. Full hashes identify immutable input bytes; local hashes are not external signatures.", ["Artifact", "SHA-256 or Git commit"], evidence_rows, size=8))
    append_elements([heading("D.4 Access to the original evidence", 2),
        paragraph("Repository: https://github.com/Faraz-NIT/MasterDissertation"),
        paragraph("Evidence guide: study_results/README.md. Final source reports: study_results/v1/M5_six_hour_study_report.md and study_results/v2/M5_v2_pilot_report.md. Run tables: M5_six_hour_results.csv and M5_v2_results.csv in those respective folders. Reassemble and verify the complete archives with scripts/study_delivery.py; its optional restore argument recreates the original results and prepared-data paths."),
        paragraph("This dissertation is a new integrated document. The uploaded source Word file, revised source HTML, original experiment reports, captured results and graph bytes remain preserved. The distinction allows a reviewer to inspect both the source evidence and the later interpretation.")])

    # Cache a complete major-heading contents list; page numbers are filled after
    # rendering by scripts/validate_integrated_dissertation.py.
    major = [p.text for p in document.paragraphs if p.style.name == "Heading 1"]
    for title in major:
        run = OxmlElement("w:r")
        text = OxmlElement("w:t")
        text.text = title
        run.append(text)
        field.append(run)
        break_run = OxmlElement("w:r")
        break_run.append(OxmlElement("w:br"))
        field.append(break_run)
    source_headings = [Paragraph(e, document).text for e in originals if e.tag == qn("w:p") and Paragraph(e, document).style.name.startswith("Heading ")]
    document.save(TARGET)
    manifest = {
        "status": "BUILT_PENDING_RENDER_QA",
        "created_at_local": datetime.now(ZoneInfo("Europe/Paris")).isoformat(),
        "source_docx": str(SOURCE.relative_to(ROOT)), "source_sha256": sha(SOURCE),
        "output_docx": str(TARGET.relative_to(ROOT)),
        "completed_v1_runs": len(v1), "completed_v2_runs": len(v2),
        "completed_runs_in_appendix": len(v1) + len(v2),
        "forecast_cases_in_appendix": len(scores),
        "figure_count": len(used_figures), "figures": used_figures,
        "tables": generated_tables, "major_headings": major,
        "source_headings_after_targeted_renaming": source_headings,
        "original_reference_count": sum(bool(Paragraph(e, document).text.strip()) for e in originals[292:346]),
        "added_evidence_references": artifact_refs,
        "comparison_note": "No studies or horizons pooled; no significance, field ROI or human-audit claim.",
        "recovery_cost_reduction_pct": round(100 * (1 - collapse_after.cost / collapse_before.cost), 2),
        "recovery_fill_improvement_pp": round(100 * (collapse_after.fill_rate - collapse_before.fill_rate), 2),
    }
    (OUT / "dissertation_build_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"status": manifest["status"], "docx": str(TARGET), "figures": 25, "appendix_runs": 404,
                      "paragraphs": len(document.paragraphs), "tables": len(document.tables)}, indent=2))


if __name__ == "__main__":
    main()
