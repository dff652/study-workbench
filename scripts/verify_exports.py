#!/usr/bin/env python3
"""Check the five local v3 exports, preserving private structural and page evidence."""
import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
import subprocess
import sys
import zipfile

from lxml import etree
from PIL import Image, ImageChops, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.exports.contracts import canonical, digest, document_dict, snapshot_id
from app.exports.rich import RichBreak, parse_rich
from app.exports.snapshots import private_directory, runtime_fingerprint, verify_snapshot, write_private
from scripts.export_legacy_packet import load_packet

MATH_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/math'
WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'m': MATH_NS, 'w': WORD_NS}


def run(*args):
    result = subprocess.run([str(arg) for arg in args], capture_output=True, timeout=60, check=True)
    return result.stdout.decode()


def ast_sequence(node):
    if node[0] == 'r':
        return [item for child in node[1:] for item in ast_sequence(child)]
    if node[0] == 't':
        return [('t', node[1])]
    return [(node[0], ast_sequence(node[1]), ast_sequence(node[2]))]


def omml_sequence(parent):
    result = []
    for child in parent:
        tag = etree.QName(child).localname
        if tag == 'r':
            result.append(('t', ''.join(child.xpath('.//m:t/text()', namespaces=NS))))
        elif tag in {'f', 'sSup', 'sSub'}:
            kind, first, second = {'f': ('f', 'num', 'den'), 'sSup': ('u', 'e', 'sup'), 'sSub': ('d', 'e', 'sub')}[tag]
            result.append((kind, omml_sequence(child.find(f'm:{first}', NS)), omml_sequence(child.find(f'm:{second}', NS))))
        else:
            raise ValueError(f'Unexpected editable math element: {tag}')
    return result


def word_checks(document, path, baseline):
    expected = [ast_sequence(block.content) for page in document.pages for block in page if block.kind == 'math']
    for candidate in (path, baseline):
        with zipfile.ZipFile(candidate) as archive:
            assert archive.testzip() is None, 'Word ZIP CRC failed'
            root = etree.fromstring(archive.read('word/document.xml'))
            equations = [omml_sequence(eq) for eq in root.xpath('//m:oMath', namespaces=NS)]
            assert equations == expected, 'Word formula content or fraction/superscript/subscript structure differs'
    expected_text = []
    for page in document.pages:
        for block in page:
            if block.kind == 'table':
                values = [cell for row in block.content[0] for cell in row]
            elif isinstance(block.content, str):
                values = [block.content]
            else:
                continue
            expected_text.extend(''.join('\n' if isinstance(event, RichBreak) else event.text for event in parse_rich(value)) for value in values)
    # Re-read the new document: the baseline loop intentionally checks both formula structures.
    with zipfile.ZipFile(path) as archive:
        root = etree.fromstring(archive.read('word/document.xml'))
        actual_text = []
        for paragraph in root.xpath('//w:p', namespaces=NS):
            value = ''.join('\n' if etree.QName(node).localname == 'br' else node.text or ''
                            for node in paragraph.xpath('.//w:t | .//w:br[not(@w:type="page")]', namespaces=NS))
            if value.strip():
                actual_text.append(value)
        assert actual_text == expected_text, 'Word paragraph/table text differs from source snapshot'
        assert len(root.xpath('//w:br[@w:type="page"]', namespaces=NS)) == len(document.pages) - 1
        footer = etree.fromstring(archive.read('word/footer1.xml'))
        fields = footer.xpath('//w:fldSimple/@w:instr', namespaces=NS)
        assert fields == ['PAGE', 'NUMPAGES'], 'Word footer must use dynamic page fields'
    return {'editable_equations': len(expected), 'source_text_blocks': len(expected_text), 'office_pagination_verified': False}


def pdf_checks(path, expected_pages):
    info = run('pdfinfo', path)
    assert f'Pages:           {expected_pages}' in info, 'PDF page count differs'
    bbox = etree.fromstring(run('pdftotext', '-bbox', path, '-').encode())
    pages = bbox.xpath('//*[local-name()="page"]')
    assert len(pages) == expected_pages
    count = 0
    for page in pages:
        width, height = float(page.get('width')), float(page.get('height'))
        assert abs(width - 595.276) < 0.1 and abs(height - 841.89) < 0.1
        for word in page.xpath('.//*[local-name()="word"]'):
            x0, x1, y0, y1 = (float(word.get(key)) for key in ('xMin', 'xMax', 'yMin', 'yMax'))
            assert 46 <= x0 <= x1 <= width - 46 and 35 <= y0 <= y1 <= height - 15, 'PDF text leaves printable bounds'
            assert '\ufffd' not in ''.join(word.itertext()), 'PDF text contains replacement characters'
            count += 1
    fonts = run('pdffonts', path).splitlines()[2:]
    # Current renderer identifies ReportLab faces by verified file digest so
    # separately subsetted documents cannot accidentally share a cached face.
    embedded = [line for line in fonts if 'StudyWorkbench' in line or 'DejaVu' in line
                or re.search(r'(?:^|\+)SWB[0-9a-f]{60}\b', line)]
    assert embedded and all('yes' in line.split()[3:-2] for line in embedded), 'Required fonts must be embedded'
    return {'pages': len(pages), 'bbox_words': count, 'embedded_fonts': embedded}


def preview_comparison(new_pdf, old_pdf, count, directory):
    directory.mkdir(mode=0o700)
    for label, pdf in (('new', new_pdf), ('baseline', old_pdf)):
        run('pdftoppm', '-r', '90', '-png', pdf, directory / label)
    records, thumbs = [], []
    for index in range(1, count + 1):
        new_path = sorted(directory.glob('new-*.png'))[index - 1]
        old_path = sorted(directory.glob('baseline-*.png'))[index - 1]
        with Image.open(new_path) as new, Image.open(old_path) as old:
            assert new.size == old.size
            crop = (0, 0, new.width, int(new.height - 50 * 90 / 72))
            diff = ImageChops.difference(new.crop(crop), old.crop(crop)).convert('RGB')
            pixels = sum(pixel != (0, 0, 0) for pixel in diff.get_flattened_data())
            records.append({'page': index, 'body_differing_pixels': pixels, 'body_pixels': diff.width * diff.height})
            thumb = new.convert('RGB')
            thumb.thumbnail((360, 510))
            thumbs.append(thumb.copy())
    columns = min(3, count)
    rows = (count + columns - 1) // columns
    sheet = Image.new('RGB', (columns * 380, rows * 540), '#d8d8d8')
    pen = ImageDraw.Draw(sheet)
    for index, thumb in enumerate(thumbs):
        x, y = (index % columns) * 380 + 10, (index // columns) * 540 + 24
        sheet.paste(thumb, (x, y))
        pen.text((x, y - 18), f'Page {index + 1}', fill='black')
    sheet.save(directory / 'contact.png')
    for path in directory.iterdir():
        path.chmod(0o600)
    return records


def numeric_practice_checks(answer_document):
    results = [Fraction(sum(10*k**3 for k in (2, 5, 8)), sum(12*k**3 for k in (2, 5, 8))),
        Fraction(sum(k*(k+2) for k in range(4, 17, 2))),
        sum((Fraction(1, k*(k+3)) for k in (4, 7, 10, 13)), Fraction()),
        sum(((-1)**(k+1) * Fraction(2*k+1, k*(k+1)) for k in range(1, 7)), Fraction()),
        Fraction(4 + 3*(20-1)),
        sum((Fraction(1, k*(k+1)//2) for k in range(1, 11)), Fraction()),
        sum((Fraction(1, k*(k+1)*(k+2)) for k in range(3, 9)), Fraction()),
        Fraction(247**2 - 246*248)]
    assert results == [Fraction(5,6), Fraction(952), Fraction(1,16), Fraction(6,7), Fraction(61), Fraction(20,11), Fraction(13,360), Fraction(1)]
    headings = [block.content for page in answer_document.pages for block in page if block.kind == 'h']
    answer_headings = [heading for heading in headings if heading[:1].isdigit()]
    assert len(answer_headings) == 8
    for heading, result in zip(answer_headings, results):
        assert str(result) in heading, 'Computed answer differs from the parent heading'
    assert '3n＋1' in answer_headings[4]
    state, sequence = 19, [19]
    for _ in range(5):
        if state % 2:
            state = 3*state+1
        else:
            while state % 2 == 0:
                state //= 2
        sequence.append(state)
    assert sequence == [19, 58, 29, 88, 11, 34]
    for n in range(1, 21):
        assert sum(k*k for k in range(1, n+1)) == n*(n+1)*(2*n+1)//6
        assert sum(k**3 for k in range(1, n+1)) == (n*(n+1)//2)**2
        assert sum(k*(k+1)//2 for k in range(1, n+1)) == n*(n+1)*(n+2)//6
        assert sum(k*(k+1) for k in range(1, n+1)) == n*(n+1)*(n+2)//3
        assert sum(k*(k+1)*(k+2) for k in range(1, n+1)) == n*(n+1)*(n+2)*(n+3)//4
        for d in range(1, 4):
            assert Fraction(1, n*(n+d)) == (Fraction(1,n)-Fraction(1,n+d))/d
            assert n*(n+d) == (n*(n+d)*(n+2*d) - (n-d)*n*(n+d))//(3*d)
    return {'practice_answers': [str(value) for value in results], 'custom_G_sequence': sequence,
            'identity_samples': {'n': [1,20], 'd': [1,3], 'checks': 220},
            'scope': 'Eight recomputed numerical answers, the stated custom G rule and 220 finite identity samples; not a general symbolic proof or a learning evaluation.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet', required=True, type=Path)
    parser.add_argument('--output-root', default=ROOT / 'exports/a2-v3', type=Path)
    parser.add_argument('--report-root', required=True, type=Path)
    args = parser.parse_args()
    documents, _, packet = load_packet(args.packet)
    report_root = private_directory(args.report_root)
    runtime = runtime_fingerprint()
    results = []
    for index, document in enumerate(documents, 1):
        inputs = {'document': document_dict(document), 'runtime': runtime, 'font_profile': packet['font_profile']}
        export_id = digest(canonical(inputs))
        directory = args.output_root / f'{document.document_id}-{export_id[:24]}'
        manifest = verify_snapshot(directory)
        assert manifest['inputs'] == inputs and manifest['snapshot_id'] == snapshot_id(document)
        results.append({'document_id': document.document_id, 'export_id': export_id, 'directory': str(directory),
            'pdf': pdf_checks(directory / 'document.pdf', len(document.pages)),
            'word': word_checks(document, directory / 'document.docx', args.packet / f'baseline-{index:02d}.docx'),
            'page_comparison': preview_comparison(directory / 'document.pdf', args.packet / f'baseline-{index:02d}.pdf', len(document.pages), report_root / document.document_id)})
    report = {'packet_id': packet['packet_id'], 'documents': results, 'numeric_checks': numeric_practice_checks(documents[4]),
              'verification_script_sha256': digest(Path(__file__).read_bytes()),
              'automated_checks_passed': True, 'manual_visual_review': 'pending', 'archive_complete': False}
    write_private(report_root / 'verification.local.json', report)
    print(json.dumps({'report': str(report_root / 'verification.local.json'), 'pdf_pages': sum(r['pdf']['pages'] for r in results),
                      'word_equations': sum(r['word']['editable_equations'] for r in results), 'manual_visual_review': 'pending'}))


if __name__ == '__main__':
    main()
