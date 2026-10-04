#!/usr/bin/env python3
"""Exercise a reviewed private sample through the offline skill and native workflows."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', required=True, type=Path)
    parser.add_argument('--skill-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    from verify_business import require_owned_database
    require_owned_database(os.environ.get('SWB_TEST_OWNER', ''))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from app.exports.contracts import canonical, digest, PURPOSES
    from app.exports.snapshots import private_directory, write_private
    from app.domain.arithmetic import check_arithmetic, formula_ast
    from app.persistence import services as core
    from app.persistence.models import EntityRecord, RevisionRecord
    from app.printing import packets, services as printing
    from app.printing.models import TeachingDiagramRevision
    from app.web import knowledge_services, services as materials
    from app.web.images import original_bbox
    from app.workflows import services as workflows
    from scripts.prepare_skill_exchange import prepare

    trial = json.loads(args.trial.read_bytes())
    assert trial['schema'] == 'study-workbench.geometry-trial.v1'
    assert trial['family_confirmation'] is False and trial['learner_evidence'] == 'not_recorded'
    output = private_directory(args.output.resolve())
    if any(output.iterdir()): raise RuntimeError('A fresh private output directory is required')
    photo = trial['photo']
    raw = Path(trial['photo_path']).read_bytes()
    assert len(raw) == photo['size'] and digest(raw) == photo['sha256']
    batch = 'skill-trial-' + uuid4().hex
    sources = {'schema_version': 'swf.sources.v1', 'batch_id': batch, 'sources': [
        {'source_id': 'original', 'sha256': photo['sha256'], 'width': photo['width'], 'height': photo['height'], 'token': 'photo-01'}]}
    content = {'schema_version': 'swf.workbench-content.v1', 'batch_id': batch, 'questions': [], 'diagrams': []}
    documents = []
    catalog = {'schema_version': 'swf.catalog.v1', 'batch_id': batch, 'entries': []}
    block_lists = {purpose: [{'kind': 'p', 'content': '主代理核定的真实几何小样；学习来源和独立性未知。', 'role': 'instruction'}] for purpose in PURPOSES}
    asset_root = private_directory(output / 'assets')
    for index, spec in enumerate(trial['questions']):
        identity = f'q{index + 1}'
        refs = [{'source_id': 'original', 'bbox': list(original_bbox(s['display_bbox'], photo['width'], photo['height'], s['rotation']))} for s in spec['sources']]
        formulas = []
        for expression in spec['formulas']:
            left, right = expression.split('=')
            assert check_arithmetic(left.strip(), right.strip())['matches'] is True
            formulas.append(['r', formula_ast(left.strip()), ['t', '='], formula_ast(right.strip())])
        proposal = {'printed_text': spec['text'], 'missing_fields': [], 'nodes': [
            {'kind': 'method', 'data': {'name': '连续使用勾股关系', 'conditions': '两个相连的直角三角形，已知三条边',
             'steps': '先求共享斜边的平方\n再求外层斜边的平方', 'notes': '仅用于家长整理，不进入独立题面'}}],
            'answer': {'body': spec['answer_body'], 'formulas': formulas, 'basis': '主代理独立复算两次勾股；不代表孩子掌握'}}
        content['questions'].append({'id': identity, 'draft': {'schema_version': 'swb.material-draft.v1',
            'original_number': spec['number'], 'sources': refs, 'proposal': proposal}})
        catalog['entries'].append({'id': identity, 'number': spec['number'], 'source_ids': ['original']})
        for purpose in ('classification_index', 'independent_practice', 'parent_answers'):
            block_lists[purpose].append({'kind': 'p', 'content': spec['text'], 'role': 'question'})
        block_lists['knowledge_summary'].append({'kind': 'p', 'content': '连续使用勾股关系：先求共享边，再求外层边。', 'role': 'method'})
        for placement in ('question', 'answer'):
            png, vector = Path(spec[placement + '_png']), Path(spec[placement + '_vector'])
            for asset in (png, vector):
                if not (asset_root / asset.name).exists(): write_private(asset_root / asset.name, asset.read_bytes())
            alt = spec['number'] + (' 原题重绘；新增字母仅用于定位' if placement == 'question' else ' 解析图')
            content['diagrams'].append({'id': identity + '.' + placement + '-diagram', 'question': identity,
                'placement': placement, 'png_key': png.name, 'vector_key': vector.name, 'source': refs[1], 'alt': alt,
                'conditions': spec['conditions'], 'width_points': 300, 'min_label_points': 16,
                'independent_safe': placement == 'question', 'basis': '主代理逐项对照原图核对；未替代家庭确认'})
            block = {'kind': 'diagram', 'role': placement, 'content': {'storage_key': png.name,
                'sha256': digest(png.read_bytes()), 'source_ref': identity + ':original', 'alt': alt,
                'width_mm': 300 * 25.4 / 72, 'no_hint_confirmed': placement == 'question'}}
            block_lists['parent_answers'].append(deepcopy(block))
            if placement == 'question': block_lists['independent_practice'].append(deepcopy(block))
        block_lists['parent_answers'].append({'kind': 'p', 'content': spec['answer_body'], 'role': 'answer'})
        block_lists['parent_answers'].extend({'kind': 'math', 'content': f, 'role': 'answer'} for f in formulas)
    for n, purpose in enumerate(sorted(PURPOSES)):
        documents.append({'schema_version': 'swf.print.v1', 'document_id': f'skill-trial-{n}', 'title': '真实几何小样',
            'purpose': purpose, 'pages': [block_lists[purpose]], 'source': {'source_id': batch,
            'sha256': digest(canonical(catalog)), 'state': 'draft', 'revision_id': None}})
    packet = {'schema_version': 'swf.packet.v1', 'batch_id': batch, 'sources_sha256': digest(canonical(sources)),
        'catalog_sha256': digest(canonical(catalog)), 'documents': documents, 'omitted_purposes': []}
    for name, value in [('content', content), ('sources', sources), ('catalog', catalog), ('packet', packet)]:
        write_private(output / (name + '.local.json'), canonical(value))
    tool = args.skill_root.resolve() / 'skills/study-material-workflow/scripts/export_content_records.py'
    result = subprocess.run([sys.executable, str(tool), '--content', str(output / 'content.local.json'),
        '--sources', str(output / 'sources.local.json'), '--asset-root', str(asset_root), '--output', str(output / 'records.local.json')],
        env={k: v for k, v in os.environ.items() if not k.startswith('SWB_') and k != 'DJANGO_SETTINGS_MODULE'},
        capture_output=True, text=True, check=True, timeout=60)
    assert json.loads(result.stdout)['database_opened'] is False
    records = json.loads((output / 'records.local.json').read_bytes())
    actor = get_user_model().objects.create_user(username='temporary-skill-' + uuid4().hex[:12])
    hid = 'temporary-skill-' + uuid4().hex
    core.create_household(actor, hid)
    material = materials.create_material(actor, hid, '真实 skill 几何小样', uuid4().hex)
    upload_key = uuid4().hex
    def upload(): return materials.upload_page(actor, material.pk, SimpleUploadedFile('original.jpg', raw, content_type='image/jpeg'), upload_key)
    uploaded = upload()
    assert upload() == uploaded
    mapping = {'schema_version': 'swb.skill-page-map.v1', 'pages': [{'source_id': 'original', 'page_id': uploaded['page_id'], 'sha256': photo['sha256']}]}
    value = prepare(sources, catalog, packet, records, mapping, ledger={'family_confirmation': False, 'learner_evidence': 'not_recorded'})
    write_private(output / 'exchange.local.json', canonical(value))
    request = uuid4().hex
    job = workflows.create(actor, material.pk, request_key=request, proposal=value)
    assert workflows.create(actor, material.pk, request_key=request, proposal=value).pk == job.pk
    expected, confirm_key = workflows.context(job), uuid4().hex
    job = workflows.action(actor, job.pk, action='confirm', expected=expected, request_key=confirm_key,
        reason='主代理对照已核定原图和数学成果验收；不是家庭确认')
    assert workflows.action(actor, job.pk, action='confirm', expected=expected, request_key=confirm_key,
        reason='主代理对照已核定原图和数学成果验收；不是家庭确认').pk == job.pk
    questions = []
    for item in content['questions']:
        saved = job.result['mapping'][item['id'] + '.question']
        q = RevisionRecord.objects.select_related('entity').get(pk=saved['revision_id'])
        detail = knowledge_services.question_detail(actor, q.entity_id)
        links = detail['history'][0].web_links
        assert len(links) == 1
        assert knowledge_services.node_detail(actor, links[0]['node_revision'].entity_id)['links']
        assert all(ref['image_sha256'] == photo['sha256'] for ref in q.payload['evidence_refs'])
        questions.append(q)
    assert TeachingDiagramRevision.objects.filter(household_id=hid).count() == 2 * len(questions)
    assert {q.pk for q in materials.page_detail(actor, uploaded['page_id'])['questions']} == {q.entity_id for q in questions}
    assert packets.readiness(actor, material.pk)['ready']
    job = workflows.action(actor, job.pk, action='queue', expected=workflows.context(job), request_key=uuid4().hex)
    assert workflows.execute_next().pk == job.pk
    job = workflows.detail(actor, job.pk)
    assert job.state == 'output_check', job.error_code
    _, manifest = packets.read(actor, material.pk, job.result['packet_id'])
    books = []
    office = {'documents': []}
    export_root = private_directory(ROOT / 'exports' / ('skill-trial-' + batch))
    for book in manifest['books']:
        target = private_directory(output / book['label'])
        office_target = private_directory(export_root / book['label'])
        for name in book['files']:
            body = printing.snapshot_file(actor, book['snapshot_id'], name).read_bytes()
            write_private(target / name, body)
            write_private(office_target / name, body)
        doc = json.loads((target / 'content.json').read_bytes())
        blocks = [block for page in doc['pages'] for block in page]
        diagrams = [b for b in blocks if b['kind'] == 'diagram']
        if book['purpose'] == 'independent_practice':
            assert len(diagrams) == len(questions) and all(b['role'] == 'question' for b in diagrams)
            assert all(b['role'] not in {'answer', 'method', 'assessment'} for b in blocks)
            assert all(s['answer_body'] not in json.dumps(doc, ensure_ascii=False) for s in trial['questions'])
        if book['purpose'] == 'parent_answers': assert len(diagrams) == 2 * len(questions)
        with zipfile.ZipFile(target / 'document.docx') as word:
            assert len([n for n in word.namelist() if n.startswith('word/media/')]) == len(diagrams)
        books.append({'purpose': book['purpose'], 'pages': len(doc['pages']), 'diagrams': len(diagrams)})
        office['documents'].append({'directory': str(office_target)})
    archive = packets.archive(actor, material.pk, job.result['packet_id'])
    with zipfile.ZipFile(archive) as z: assert len(z.namelist()) == 21
    archive.seek(0); write_private(output / 'five-books.zip', archive.read()); archive.close()
    job = workflows.action(actor, job.pk, action='check_output', expected=workflows.context(job), request_key=uuid4().hex,
        reason='机器内容／资产校验完成，实际版式另有对照报告', checks={'pdf': True, 'docx': True, 'purposes': True})
    assert job.state == 'complete'
    assert not EntityRecord.objects.filter(household_id=hid, kind__in=('learner', 'attempt', 'assessment', 'erratum')).exists()
    assert digest(Path(trial['photo_path']).read_bytes()) == photo['sha256']
    report = {'schema_version': 'swb.skill-trial-result.v1', 'status': 'pass', 'books': books,
        'question_count': len(questions), 'diagram_count': len(content['diagrams']), 'record_count': len(records['records']),
        'source_sha256': photo['sha256'], 'exchange_sha256': digest(canonical(value)), 'tool_sha256': digest(tool.read_bytes()),
        'traceability': 'bidirectional', 'creation_and_confirmation_replay': 'passed',
        'learner_evidence': 'not_recorded', 'family_confirmation': False, 'actual_ms_word': 'not_tested', 'real_model_calls': 0}
    write_private(output / 'verification.local.json', canonical(report))
    write_private(output / 'word-input.local.json', canonical(office))
    print(json.dumps({'status': 'pass', 'questions': len(questions), 'diagrams': len(content['diagrams']), 'books': books}))


if __name__ == '__main__': main()
