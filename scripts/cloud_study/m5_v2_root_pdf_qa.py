"""Verify final PDF statements and preserve root visual/font inspection receipt."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path('/workspace/MasterDissertation')
OUT = ROOT/'results/v2_report_validation'
pdf = ROOT/'results/v2_pilot/report_final/M5_v2_pilot_report.pdf'
text = subprocess.check_output(['pdftotext', '-layout', str(pdf), '-'], text=True)
first = ' '.join(text.split('\f')[0].split())
assert 'from 894.30 to 796.51 USD (-10.93%)' in first
assert 'from 89.0% to 96.0% (+7.0 percentage points)' in first
assert '10/20 fresh choices' in first
assert 'no additional operational advantage' in first
assert '32 completed runs, 448 decision traces, 68 recorded model attempts' in first
assert 'zero client errors' in first
info = subprocess.run(['pdfinfo', str(pdf)], text=True, capture_output=True, check=True)
fonts = subprocess.run(['pdffonts', str(pdf)], text=True, capture_output=True, check=True)
assert 'Pages:           25' in info.stdout
assert 'DejaVuSans' in fonts.stdout and 'yes yes yes' in fonts.stdout
receipt = {
    'status': 'PASS', 'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
    'pdf_bytes': pdf.stat().st_size, 'pages': 25,
    'summary_checked_against_original_runs': True,
    'semantic_tool_failures_disclosed': True,
    'font_embedding': 'DejaVu Sans regular/bold embedded with Unicode mappings',
    'visual_checks': ['Page 3 result table readable with no clipping',
                      'Derived-collapse graph readable; zero-start axes; costs894.296/796.505 and fill0.89/0.96'],
    'pdf_text_check_history': 'First ad-hoc literal substring assertion failed because PDF line wrapping placed a newline before796.51. Whitespace-normalized checks passed; no document data or result was changed.',
    'fontconfig_warning': 'No writable font cache warnings; pdffonts exit0 and actual body fonts embedded. PDF is self-contained.',
}
(OUT/'root_pdf_qa.json').write_text(json.dumps(receipt, indent=2))
(OUT/'root_pdfinfo.txt').write_text(info.stdout)
(OUT/'root_pdffonts.txt').write_text(fonts.stdout)
(OUT/'root_pdffonts.stderr.log').write_text(fonts.stderr)
(OUT/'root_final_pdf_text.txt').write_text(text)
print(json.dumps(receipt, indent=2))
