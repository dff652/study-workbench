#!/usr/bin/env python3
"""Verify a locally reviewed small geometry sample in the owned disposable PG.

Private JSON supplies photos, text, regions and matched PNG/vector drawings.
No model calls, historical script execution, permanent imports or NAS writes.
"""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    from verify_business import require_owned_database
    require_owned_database(os.environ.get('SWB_TEST_OWNER', ''))
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from app.exports.contracts import canonical, digest
    from app.exports.snapshots import private_directory, write_private
    from app.domain.arithmetic import check_arithmetic, formula_ast
    from app.persistence import services as core
    from app.persistence.models import EntityRecord, RevisionRecord
    from app.printing import packets, services as printing
    from app.printing.models import TeachingDiagramRevision
    from app.web import knowledge_services, services as materials
    from app.web.models import QuestionSource

    trial = json.loads(args.trial.read_bytes())
    assert trial['schema'] == 'study-workbench.geometry-trial.v1'
    assert 1 <= len(trial['questions']) <= 5
    assert trial['family_confirmation'] is False and trial['learner_evidence'] == 'not_recorded'
    output = args.output.resolve()
    private_directory(output)
    if any(output.iterdir()):
        raise RuntimeError('Use a new private output directory; never overwrite trial evidence')
    actor = get_user_model().objects.create_user(username='temporary-geometry-' + uuid4().hex[:12])
    household_id = 'temporary-geometry-' + uuid4().hex
    core.create_household(actor, household_id)
    material_id = materials.create_material(actor, household_id, '真实几何小样核对', uuid4().hex).pk
    raw = Path(trial['photo_path']).read_bytes()
    assert len(raw) == trial['photo']['size'] and digest(raw) == trial['photo']['sha256']
    upload_key = uuid4().hex
    def upload():
        return materials.upload_page(actor, material_id,
            SimpleUploadedFile(Path(trial['photo_path']).name, raw, content_type='image/jpeg'), upload_key)
    uploaded = upload()
    assert upload() == uploaded
    page_id = uploaded['page_id']
    question_ids = []
    questions = []
    client = Client(enforce_csrf_checks=True)
    client.force_login(actor)
    for spec in trial['questions']:
        sources = [{**value, 'page_id': page_id,
            'preview_sha256': materials.preview_file(actor, page_id, value['rotation']).sha256}
            for value in spec['sources']]
        question_key = uuid4().hex
        values = dict(printed_text=spec['text'], original_number=spec['number'], sources=sources,
            request_key=question_key, reason='主代理对照真实原图转录；不代表家庭或学习者确认', confirm=True)
        saved = materials.save_question(actor, material_id, **values)
        assert materials.save_question(actor, material_id, **values) == saved
        question = RevisionRecord.objects.select_related('entity').get(pk=saved['revision_id'])
        questions.append(question)
        question_ids.append(question.pk)
        metadata = QuestionSource.objects.get(revision=question)
        assert len(metadata.sources) == len(question.payload['evidence_refs']) == 2
        for source, ref in zip(metadata.sources, question.payload['evidence_refs']):
            region = RevisionRecord.objects.get(pk=ref['region_revision_id'])
            assert region.original_image.sha256 == trial['photo']['sha256']
            assert list(region.payload['geometry']) == source['original_bbox']
        formulas = []
        for expression in spec['formulas']:
            left, right = expression.split('=')
            assert check_arithmetic(left.strip(), right.strip())['matches'] is True
            formulas.append(['r', formula_ast(left.strip()), ['t', '='], formula_ast(right.strip())])
        printing.save_answer(actor, household_id, question.pk, body=spec['answer_body'], formulas=formulas,
            basis='主代理独立复算两次勾股；仅验证答案内容，不推断孩子掌握',
            expected=printing.answer_context(question), request_key=uuid4().hex, confirm=True)
        for placement in ('question', 'answer'):
            url = f'/prints/diagrams/{question.pk}/'
            response = client.get(url)
            assert response.status_code == 200
            token = re.search(r'name="context" value="([^"]+)"', response.content.decode()).group(1)
            png = Path(spec[placement + '_png'])
            vector = Path(spec[placement + '_vector'])
            values = {'context': token, 'request_key': uuid4().hex, 'placement': placement,
                'source_region_id': question.payload['evidence_refs'][1]['region_revision_id'],
                'png_upload': SimpleUploadedFile(png.name, png.read_bytes(), content_type='image/png'),
                'vector_upload': SimpleUploadedFile(vector.name, vector.read_bytes()),
                'alt': spec['number'] + (' 原题重绘；新增字母仅用于定位' if placement == 'question' else ' 解析图'),
                'conditions': '\n'.join(spec['conditions']), 'width_points': '300', 'min_label_points': '16',
                'content_checked': 'on', 'basis': '主代理逐项对照原图；直角来自题干，数值复算，未代替家庭确认',
                'csrfmiddlewaretoken': client.cookies['csrftoken'].value}
            if placement == 'question':
                values['independent_safe'] = 'on'
            response = client.post(url, values)
            assert response.status_code == 302, response.content.decode()

    def accept(result):
        row = RevisionRecord.objects.select_related('entity').get(pk=result['revision_id'])
        context = core.review_context(actor, household_id, row.pk)
        core.review_revision(actor, household_id, row.pk, action='accept',
            reason='主代理核定来源和数学内容；未代替学习者证据', expected_head=context['expected_head'],
            expected_dependencies=context['expected_dependencies'], expected_decision_id=context['expected_decision_id'],
            request_key=uuid4().hex)
        return row

    node = accept(knowledge_services.save_node(actor, household_id, 'method', data={
        'name': '连续使用勾股关系', 'conditions': '两个相连的直角三角形；已知三条边',
        'steps': '先求共享斜边的平方\n再求外层斜边的平方', 'notes': '用于家长知识整理，不进入无提示题面',
        'sources': sources}, reason='主代理按真实题干核定方法', request_key=uuid4().hex))
    for question in questions:
        accept(knowledge_services.create_link(actor, household_id, kind='method', node_revision_id=node.pk,
            question_revision_id=question.pk, role='primary', request_key=uuid4().hex, reason='真实原题到主方法关联'))
        detail = knowledge_services.question_detail(actor, question.entity.pk)
        assert any(row['node_revision'].entity_id == node.entity_id for row in detail['history'][0].web_links)
    node_detail = knowledge_services.node_detail(actor, node.entity_id)
    assert len(node_detail['links']) == len(questions)
    page_detail = materials.page_detail(actor, page_id)
    assert {q.pk for q in page_detail['questions']} == {q.entity_id for q in questions}
    assert page_detail['page'].image.payload['width'] == trial['photo']['width']
    assert page_detail['page'].image.payload['height'] == trial['photo']['height']
    state = packets.readiness(actor, material_id)
    assert state['ready'] and state['content_gaps'] == []
    packet_id = packets.generate(actor, material_id)
    assert packets.generate(actor, material_id) == packet_id
    _, manifest = packets.read(actor, material_id, packet_id)
    assert manifest['question_revisions'] == question_ids and manifest['evidence_scope'] == 'not_recorded'
    assert len(manifest['diagram_revisions']) == 2 * len(questions)
    book_reports = []
    for book in manifest['books']:
        target = private_directory(output / book['label'])
        for name in book['files']:
            write_private(target / name, printing.snapshot_file(actor, book['snapshot_id'], name).read_bytes())
        content = json.loads((target / 'content.json').read_bytes())
        blocks = [b for page in content['pages'] for b in page]
        diagrams = [b for b in blocks if b['kind'] == 'diagram']
        if book['purpose'] == 'independent_practice':
            assert len(diagrams) == len(questions) and all(b['role'] == 'question' for b in diagrams)
            assert all(b['role'] not in ('answer', 'assessment', 'method') for b in blocks)
            assert all(q['answer_body'] not in json.dumps(content, ensure_ascii=False) for q in trial['questions'])
        if book['purpose'] == 'parent_answers':
            assert len(diagrams) == 2 * len(questions)
        if book['purpose'] == 'evidence_report':
            assert not diagrams and '未知' in json.dumps(content, ensure_ascii=False)
        with zipfile.ZipFile(target / 'document.docx') as docx:
            assert len([n for n in docx.namelist() if n.startswith('word/media/')]) == len(diagrams)
        book_reports.append({'purpose': book['purpose'], 'pages': len(content['pages']), 'diagrams': len(diagrams)})
    archive = packets.archive(actor, material_id, packet_id)
    with zipfile.ZipFile(archive) as bundle:
        assert len(bundle.namelist()) == 21
    archive.seek(0)
    write_private(output / 'five-books.zip', archive.read())
    archive.close()
    write_private(output / 'manifest.json', canonical(manifest))
    assert not EntityRecord.objects.filter(household_id=household_id, kind__in=('learner','attempt','assessment','erratum')).exists()
    source_check = json.loads(Path(trial['source_check']).read_bytes())
    for photo in source_check['photos']:
        assert digest((Path(source_check['source_root']) / 'sources' / photo['path']).read_bytes()) == photo['sha256']
    # Preserve diagrams as separately hashed provenance; the ZIP is not a backup.
    for spec in trial['questions']:
        for field in ('question_png','question_vector','answer_png','answer_vector'):
            path = Path(spec[field]); write_private(output / path.name, path.read_bytes())
    report = {'schema': 'study-workbench.geometry-trial-result.v1', 'input_sha256': digest(args.trial.read_bytes()),
        'originals_unchanged': len(source_check['photos']), 'sample_photos': 1, 'questions': len(questions),
        'diagrams': TeachingDiagramRevision.objects.filter(household_id=household_id).count(),
        'books': book_reports, 'packet_id': packet_id, 'checks': ['upload-replay','source-regions',
            'question-replay','math-manual-review','csrf-diagram-upload','method-bidirectional-links','photo-question-backlinks',
            'fixed-revisions','five-books-repeat','independent-no-answer','docx-embedded-images',
            'zip-21','unknown-learning','all-original-hashes-unchanged'],
        'family_confirmation': False, 'learner_evidence': 'not_recorded', 'database_retention': 'disposable',
        'production_import': False, 'nas_write': False, 'model_call': False}
    write_private(output / 'verification.local.json', canonical(report))
    print(json.dumps({'geometry_trial_verified': True, 'questions': len(questions), 'books': book_reports}), flush=True)


if __name__ == '__main__':
    main()
