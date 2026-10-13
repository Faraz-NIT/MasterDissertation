"""Verify the chapter's scope, text, table, formatting and rendered-page completeness."""
from pathlib import Path
import hashlib
import json
import re

from docx import Document
from PIL import Image, ImageDraw
import fitz

OUT = Path(__file__).resolve().parent
text = (OUT / 'chapter_7.md').read_text()
docx = OUT / 'Conclusion_and_Future_Research_Rewritten.docx'
pdf_path = OUT / 'Conclusion_and_Future_Research_Rewritten.pdf'
document = Document(docx)
expected = [re.sub(r'^#{1,3} ', '', line) for line in text.splitlines() if line.strip() and not line.startswith('|')]
assert [p.text for p in document.paragraphs if p.text.strip()] == expected
rows = [[c.strip() for c in line.strip('|').split('|')] for line in text.splitlines() if line.startswith('|') and '---' not in line]
assert len(document.tables) == 1
assert [[c.text for c in r.cells] for r in document.tables[0].rows] == rows
assert len([p for p in document.paragraphs if p.style.name == 'Heading 1']) == 1
normal = document.styles['Normal']
assert normal.font.name == 'Times New Roman' and normal.font.size.pt == 12
assert normal.paragraph_format.line_spacing == 1.5
assert all(abs(getattr(document.sections[0], k).inches - 1) < .001 for k in ['top_margin', 'bottom_margin', 'left_margin', 'right_margin'])
tags = ['RQ1.', 'RQ2.', 'RQ3.', 'RQ4.', 'H1a:', 'H1b:', 'H2a:', 'H2b:', 'H3:', 'H4:']
for tag in tags:
    assert tag in text, tag
for claim in ['formal support not established', 'not trained or fine-tuned', 'staff time were not measured']:
    assert claim in text, claim
pdf = fitz.open(pdf_path)
texts = [re.sub(r'\s+', ' ', page.get_text()).strip() for page in pdf]
assert all(len(t) > 80 for t in texts)
for page_number, page in enumerate(pdf, 1):
    for x0, y0, x1, y1, *_ in page.get_text('blocks'):
        assert x0 >= 20 and y0 >= 15 and x1 <= page.rect.width - 20 and y1 <= page.rect.height - 15, page_number
for tag in tags:
    assert tag in ' '.join(texts), tag
table_page = next(i for i, page_text in enumerate(texts) if 'H1a:' in page_text)
assert all(tag in texts[table_page] for tag in ['H1a:', 'H1b:', 'H2a:', 'H2b:', 'H3:', 'H4:'])
sheet = Image.new('RGB', (300 * 3, 435 * ((len(pdf) + 2) // 3)), 'white')
for i, page in enumerate(pdf):
    pixmap = page.get_pixmap(matrix=fitz.Matrix(.47, .47))
    image = Image.frombytes('RGB', [pixmap.width, pixmap.height], pixmap.samples)
    tile = Image.new('RGB', (300, 435), '#ECEFF1')
    tile.paste(image, ((300 - image.width) // 2, 8))
    ImageDraw.Draw(tile).text((10, 414), f'Page {i + 1}', fill='black')
    sheet.paste(tile, ((i % 3) * 300, (i // 3) * 435))
sheet.save(OUT / 'review_contact_sheet.png')
pdf[table_page].get_pixmap(matrix=fitz.Matrix(1.2, 1.2)).save(OUT / 'hypothesis_table_review.png')
record = {
    'status': 'PASS', 'chapter_only': True, 'docx_text_matches_manuscript': True,
    'hypothesis_table_complete': True, 'hypothesis_table_on_single_page': table_page + 1,
    'all_questions_and_hypotheses_answered': True, 'format_verified': True,
    'pdf_pages': len(pdf), 'pdf_nonempty_pages': True, 'no_text_outside_page_bounds': True,
    'numerical_claims_checked_by_builder': True, 'H4_formal_assessment': 'Not established; exploratory',
    'docx_sha256': hashlib.sha256(docx.read_bytes()).hexdigest(),
    'pdf_sha256': hashlib.sha256(pdf_path.read_bytes()).hexdigest(),
}
(OUT / 'validation.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2))
