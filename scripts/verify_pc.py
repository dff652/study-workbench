#!/usr/bin/env python3
"""Real PC browser acceptance against an owned synthetic database and files."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_business import require_owned_database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    args = parser.parse_args()
    require_owned_database(args.owner)
    import django
    django.setup()
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import connections
    from app.persistence import services as core
    from app.persistence.models import HouseholdMember
    from app.web import services as materials
    from app.ai import services as ai
    from app.ai.models import ModelConfig, ModelRun
    from app.study.models import StudySchedule
    from PIL import Image
    from playwright.sync_api import sync_playwright, expect

    output = ROOT / 'artifacts/pc-verification' / args.owner
    output.mkdir(parents=True, mode=0o700)
    for parent in (output, output.parent, output.parent.parent): parent.chmod(0o700)
    password = secrets.token_urlsafe(24)
    actor = get_user_model().objects.create_user(username='pc-' + uuid4().hex[:10], password=password)
    house = core.create_household(actor, 'PC 合成家庭')
    second_house = core.create_household(actor, 'PC 空白家庭')
    viewer = get_user_model().objects.create_user(username='pc-viewer-' + uuid4().hex[:8], password=password)
    HouseholdMember.objects.create(household=house, user=viewer, role='viewer')
    material = materials.create_material(actor, house.pk, '合成容器验收 PC 资料', uuid4().hex)
    stream = BytesIO(); Image.new('RGB', (160, 120), 'white').save(stream, format='PNG')
    source = materials.upload_page(actor, material.pk,
        SimpleUploadedFile('synthetic.png', stream.getvalue(), content_type='image/png'), uuid4().hex)
    fixture_run = subprocess.run([sys.executable, '-c', (ROOT / 'scripts/container_business_fixture.py').read_text()], cwd=ROOT,
        input=json.dumps({'username': actor.username, 'page_id': source['page_id']}), text=True,
        capture_output=True, timeout=180)
    if fixture_run.returncode:
        (output / 'fixture-error.log').write_text(fixture_run.stderr)
        raise RuntimeError(fixture_run.stderr)
    seeded = json.loads(fixture_run.stdout); f = seeded['fixture']
    from app.web import learning_services
    second_learner = learning_services.create_profile(actor, house.pk,
        display_name='第二合成学习者', grade='', request_key=uuid4().hex)['learner_id']
    transparent = BytesIO()
    Image.new('RGBA', (12, 12), (30, 60, 120, 128)).save(transparent, format='PNG')
    from types import SimpleNamespace
    from tests.workflows.test_services import WorkflowTests
    from tests.workflows.test_assets import with_diagram
    from app.workflows import services as workflows
    proposal = with_diagram(WorkflowTests.proposal(SimpleNamespace(material=material)))
    from app.domain.arithmetic import formula_ast
    proposal['records'][2]['data']['formulas'] = [formula_ast('1/2')]
    pending = workflows.create(actor, material.pk, request_key=uuid4().hex, proposal=proposal)
    config_data = {'provider_label':'合成配置历史', 'base_url':'https://model.example.test/v1',
        'model':'synthetic-only', 'cloud_enabled':True, 'outbound_scope':'reviewed_text',
        'connection_route':'unknown', 'upstream_state':'unknown', 'known_upstream_providers':'',
        'retention_state':'unknown', 'retention_description':'', 'confirm_external_processing':True,
        'batch_budget':'1', 'reserved_per_call':'0.1', 'input_price_per_million':'1', 'output_price_per_million':'1'}
    ai.create_model_config(actor, house.pk, data=config_data)
    selection = ai.selection_context(actor, house.pk, 'question')
    model_run = ai.queue_run(actor, house.pk, task_kind='question',
        question_revision_ids=[f['question_revision']], source_revision_ids=[f['question_revision']],
        selection_token=selection['token'], request_key=uuid4().hex)
    ai.cancel_run(actor, model_run.pk)
    ai.create_model_config(actor, house.pk, data={**config_data, 'cloud_enabled':False, 'confirm_external_processing':False})
    schedule = StudySchedule.objects.get(schedule_id=f['schedule'])
    paths = [
        ('materials-index', '/materials/'),
        ('material-detail', f'/material/{material.pk}/'),
        ('page', f'/page/{f["page"]}/'), ('page-reading', f'/page/{f["page"]}/reading/'),
        ('question-new', f'/material/{material.pk}/question/new/'),
        ('question', f'/question/{f["question"]}/'), ('question-edit', f'/question/{f["question"]}/edit/'),
        ('knowledge', f'/knowledge/?household_id={house.pk}'),
        ('knowledge-unscoped-index', '/knowledge/'),
        ('knowledge-household-choice', '/knowledge/create/knowledge/'),
        ('knowledge-new', f'/knowledge/create/knowledge/?household_id={house.pk}'),
        ('method-new', f'/knowledge/create/method/?household_id={house.pk}'),
        ('question-type-new', f'/knowledge/create/question_type/?household_id={house.pk}'),
        ('knowledge-node', f'/knowledge/entity/{f["node"]}/'),
        ('knowledge-edit', f'/knowledge/entity/{f["node"]}/edit/'),
        ('knowledge-question', f'/knowledge/question/{f["question_entity"]}/'),
        ('catalogue', f'/catalogue/?household_id={house.pk}'),
        ('catalogue-unscoped-index', '/catalogue/'),
        ('catalogue-household-choice', '/catalogue/merge/'),
        ('catalogue-question', f'/catalogue/question/{f["question_entity"]}/'),
        ('question-split', f'/catalogue/question/{f["question_entity"]}/split/'),
        ('question-merge', f'/catalogue/merge/?household_id={house.pk}'),
        ('learning', f'/learning/?household={house.pk}'),
        ('profile-new', f'/learning/profile/new/?household={house.pk}'),
        ('profile', f'/learning/profile/{f["learner"]}/'),
        ('observation-new', f'/learning/observation/new/?household={house.pk}&learner={f["learner"]}'),
        ('observation', f'/learning/observation/{f["observation"]}/'),
        ('observation-edit', f'/learning/observation/{f["observation"]}/edit/'),
        ('attempt-new', f'/learning/profile/{f["learner"]}/attempt/new/'),
        ('attempt', f'/learning/attempt/{f["attempt"]}/'),
        ('attempt-edit', f'/learning/attempt/{f["attempt"]}/edit/'),
        ('attempt-correct', f'/learning/attempt/{f["attempt"]}/correct/'),
        ('assessment-new', f'/learning/attempt/{f["attempt"]}/assessment/new/'),
        ('assessment', f'/learning/assessment/{f["assessment"]}/'),
        ('assessment-edit', f'/learning/assessment/{f["assessment"]}/edit/'),
        ('study', f'/study/?household={house.pk}'),
        ('schedule-new', f'/study/learner/{f["learner_entity"]}/schedule/new/'),
        ('schedule', f'/study/schedule/{schedule.pk}/'),
        ('study-report', f'/study/learner/{f["learner_entity"]}/report/'),
        ('prints', f'/prints/?household={house.pk}'), ('arithmetic', '/prints/arithmetic/'),
        ('answer', f'/prints/answers/{f["question_revision"]}/'),
        ('erratum', f'/prints/errata/{f["question_revision"]}/'),
        ('diagrams', f'/prints/diagrams/{f["question_revision"]}/'),
        ('snapshot', f'/prints/snapshots/{f["snapshots"][1]}/'),
        ('evidence-report', f'/prints/reports/{f["learner_entity"]}/'),
        ('five-books-prepare', f'/prints/materials/{material.pk}/five-books/'),
        ('five-books', f'/prints/materials/{material.pk}/five-books/{f["packet"]}/'),
        ('members', f'/members/?household_id={house.pk}'),
        ('models', f'/ai/?household={house.pk}'), ('model-config', f'/ai/config/{house.pk}/'),
        ('model-new', f'/ai/new/{house.pk}/question/'),
        ('model-run', f'/ai/run/{model_run.pk}/'), ('model-review', f'/ai/run/{model_run.pk}/review/'),
        ('operations', f'/operations/?household={house.pk}'),
        ('retention', f'/operations/household/{house.pk}/retention/'),
        ('timing', f'/operations/household/{house.pk}/timing/new/'),
        ('help', '/help/'),
    ]
    # Capture the actual templates rendered by every native business state. This
    # makes the completeness gate independent of route names or a hand count.
    from django.test import Client
    from django.test.utils import setup_test_environment
    setup_test_environment()
    native = Client(); native.force_login(actor)
    template_map = {}
    for name, path in paths:
        result = native.get(path)
        assert result.status_code == 200, (name, result.status_code)
        template_map[name] = sorted({t.name for t in result.templates if t.name})
    login_result = Client().get('/accounts/login/')
    assert login_result.status_code == 200
    template_map['login'] = sorted({t.name for t in login_result.templates if t.name})
    expected_templates = {str(p).split('/templates/', 1)[1] for p in (ROOT / 'app').rglob('templates/**/*.html')
        if not p.name.startswith('_') and p.name not in {'base.html', 'message.html', 'mobile-help.html'}}
    covered_templates = {name for names in template_map.values() for name in names}
    assert expected_templates <= covered_templates, sorted(expected_templates - covered_templates)
    def view_for(path):
        if path.startswith(('/knowledge/', '/catalogue/')): return 'knowledge'
        if path.startswith('/prints/'): return 'documents'
        if path.startswith('/study/'): return 'progress'
        if path.startswith('/learning/'): return 'learning'
        if path.startswith(('/members/', '/ai/', '/operations/', '/help/')): return 'settings'
        return 'materials'
    def app_url(path='', view=None, household=None):
        return '/app/?' + urlencode({'view': view or view_for(path), 'household': household or house.pk,
                                    **({'screen': path} if path else {})})
    def target_key(url):
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query)
        if unquote(parts.path) == '/learning/':
            pairs = [(key, value) for key, value in pairs if key != 'learner']
        return unquote(parts.path), sorted(pairs)
    pool = ThreadPoolExecutor(max_workers=1)
    def db(fn):
        def call():
            try: return fn()
            finally: connections.close_all()
        return pool.submit(call).result(timeout=180)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    checks, matrix, errors, external, leaks = [], [], [], [], []
    server = None
    try:
        with (output / 'server.log').open('w') as log:
            server = subprocess.Popen([sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}',
                '--noreload', '--insecure'], cwd=ROOT, stdout=log, stderr=log)
            deadline = time.monotonic() + 20
            while True:
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=.3): break
                except OSError:
                    if time.monotonic() > deadline: raise RuntimeError('Owned server failed to start')
                    time.sleep(.1)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True)
                def restrict(route):
                    if route.request.url.startswith(origin + '/'): route.continue_()
                    else: external.append(route.request.url); route.abort()
                context.route('**/*', restrict)
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                def login(user):
                    page.goto(origin + '/accounts/login/')
                    if user == actor:
                        page.screenshot(path=str(output / 'login.png'), full_page=True)
                    page.locator('#id_username').fill(user.username)
                    page.locator('#id_password').fill(password)
                    page.get_by_role('button', name='登录', exact=True).click()
                    page.wait_for_url(lambda url: '/accounts/login/' not in urlsplit(url).path)
                login(actor)
                def settle_visuals():
                    # Full-page captures need stable fonts and source-image
                    # dimensions; an h1 alone can precede the image/widget layout.
                    page.evaluate('''async () => {
                        await document.fonts.ready;
                        await Promise.all([...document.querySelectorAll('main img')].map(img => {
                            img.loading = 'eager';
                            if (img.complete) {
                                if (!img.naturalWidth) throw new Error('Source image failed to load');
                                return Promise.resolve();
                            }
                            return new Promise((resolve, reject) => {
                                img.addEventListener('load', resolve, {once: true});
                                img.addEventListener('error', () => reject(new Error('Source image failed to load')), {once: true});
                            });
                        }));
                        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    }''')
                for name, path in paths:
                    with page.expect_response(lambda r: '/api/v1/workspace/page/' in r.url) as fetched:
                        page.goto(origin + app_url(path))
                    response = fetched.value
                    assert response.status == 200, (name, response.status, response.text()[:300])
                    assert target_key(response.json()['page']['url']) == target_key(path), name
                    expect(page.locator('.workspace-page')).to_be_visible()
                    expect(page.get_by_role('navigation', name='主导航')).to_be_visible()
                    expect(page.locator('.workspace-page h1'), name).to_have_count(1)
                    expect(page.locator('.workspace-page h1'), name).to_have_text(response.json()['page']['title'])
                    actual_screen = dict(parse_qsl(urlsplit(page.url).query)).get('screen', '')
                    assert target_key(actual_screen) == target_key(path), (name, actual_screen)
                    assert urlsplit(page.url).path == '/app/'
                    assert not page.locator('link[href*="web/app.css"]').count()
                    assert not page.locator('iframe').count()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), name
                    visible = page.locator('.workspace-page').inner_text()
                    codes = re.findall(r'\b(?:[0-9a-f]{8}-[0-9a-f-]{27,}|[0-9a-f]{64}|EvidencePurpose\.[A-Z_]+|swb\.[a-z.-]+\.v[12]|parent_answers|independent_practice|not_tested|accepted|observed|permission_denied|B1|A2)\b', visible)
                    if codes:
                        leaks.append({'page':name, 'codes':codes,
                            'contexts':[visible[max(0, visible.find(code)-60):visible.find(code)+len(code)+60] for code in codes]})
                    settle_visuals()
                    page.screenshot(path=str(output / (name + '.png')), full_page=True)
                    page.screenshot(path=str(output / (name + '-viewport.png')))
                    matrix.append({'page':name, 'path':path, 'width':1440, 'status':200,
                                   'templates':template_map[name],
                                   'heading':page.locator('.workspace-page h1').inner_text()})
                checks.append('all-business-page-types-in-unified-shell')
                for width in (1280, 1920):
                    page.set_viewport_size({'width':width, 'height':1000})
                    for name in ('page', 'knowledge', 'attempt', 'assessment-edit', 'model-config', 'five-books'):
                        path = dict(paths)[name]
                        page.goto(origin + app_url(path))
                        expect(page.locator('.workspace-page h1')).to_have_count(1)
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (width, name)
                        page.screenshot(path=str(output / f'{name}-{width}.png'), full_page=True)
                page.set_viewport_size({'width':1440, 'height':1000})
                checks.append('pc-1280-1440-1920-layout')
                page.goto(origin + app_url('/knowledge/?household_id=' + house.pk))
                expect(page.locator('.workspace-page')).to_be_visible()
                page.evaluate('window.__pcShellMarker = "retained"')
                page.get_by_role('navigation', name='主导航').get_by_role('button', name='设置', exact=True).click()
                expect(page.locator('.workspace-page h1')).to_contain_text('成员')
                assert page.evaluate('window.__pcShellMarker') == 'retained'
                page.go_back(); expect(page.locator('.workspace-page h1')).to_contain_text('知识')
                page.go_forward(); expect(page.locator('.workspace-page h1')).to_contain_text('成员')
                page.reload(); expect(page.locator('.workspace-page h1')).to_contain_text('成员')
                checks.append('navigation-back-forward-refresh-context')
                page.goto(origin + app_url(f'/learning/profile/{f["learner"]}/'))
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                page.get_by_label('学习者', exact=True).select_option(second_learner)
                expect(page.locator('.workspace-page h1')).to_have_text('第二合成学习者')
                assert dict(parse_qsl(urlsplit(page.url).query))['learner'] == second_learner
                page.screenshot(path=str(output / 'learner-context.png'))
                page.get_by_role('link', name='学习档案', exact=True).click()
                expect(page.get_by_label('学习者', exact=True)).to_have_value(second_learner)
                page.get_by_role('link', name='合成学习者', exact=True).click()
                expect(page.locator('.workspace-page h1')).to_have_text('合成学习者')
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                with page.expect_response(lambda r: f'/learners/{f["learner"]}/overview/' in r.url) as context_overview:
                    page.get_by_role('navigation', name='主导航').get_by_role('button', name='学习总览', exact=True).click()
                assert context_overview.value.json()['metrics']['attempt_count'] == 3
                checks.append('learner-profile-switch-keeps-evidence-context')
                # Integer report addresses must resolve to the stable learner,
                # and selecting another learner must leave the old report/plan.
                report_path = f'/study/learner/{f["learner_entity"]}/report/'
                page.goto(origin + app_url(report_path) + '&learner=' + second_learner)
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                for path in (report_path, f'/study/schedule/{schedule.pk}/'):
                    page.goto(origin + app_url(path) + '&learner=' + f['learner'])
                    expect(page.locator('.workspace-page')).to_be_visible()
                    with page.expect_response(lambda r: f'/learners/{second_learner}/progress/' in r.url) as learner_progress:
                        page.get_by_label('学习者', exact=True).select_option(second_learner)
                    assert learner_progress.value.status == 200
                    assert not dict(parse_qsl(urlsplit(page.url).query)).get('screen')
                    expect(page.get_by_label('学习者', exact=True)).to_have_value(second_learner)
                page.screenshot(path=str(output / 'learner-progress-context.png'), full_page=True)
                checks.append('learner-report-and-plan-switch-keeps-scope')
                # A household list contains plans for all learners. Stored plan
                # ownership must replace unrelated outer learner context.
                schedule_path = f'/study/schedule/{schedule.pk}/'
                page.goto(origin + app_url('/study/') + '&learner=' + second_learner)
                expect(page.get_by_label('学习者', exact=True)).to_have_value(second_learner)
                page.locator(f'a[href="{schedule_path}"]').click()
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                assert dict(parse_qsl(urlsplit(page.url).query))['learner'] == f['learner']
                page.goto(origin + app_url(schedule_path) + '&learner=' + second_learner)
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                page.reload()
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                page.goto(origin + app_url(schedule_path, household=second_house.pk) + '&learner=' + second_learner)
                expect(page.get_by_label('家庭', exact=True)).to_have_value(house.pk)
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                expect(page.locator('.workspace-page h1')).to_contain_text('合成学习者')
                settle_visuals()
                page.screenshot(path=str(output / 'schedule-owner-context.png'), full_page=True)
                for record_path in (f'/learning/attempt/{f["attempt"]}/',
                                    f'/learning/assessment/{f["assessment"]}/',
                                    f'/learning/observation/{f["observation"]}/'):
                    page.goto(origin + app_url(record_path) + '&learner=' + second_learner)
                    expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                    assert dict(parse_qsl(urlsplit(page.url).query))['learner'] == f['learner']
                checks.append('learner-record-list-direct-refresh-and-household-owner-scope')
                page.goto(origin + app_url('/operations/'))
                target_policy = f'/operations/household/{quote(second_house.pk, safe="")}/retention/'
                page.locator(f'a[href="{target_policy}"]').click()
                expect(page.get_by_label('家庭', exact=True)).to_have_value(second_house.pk)
                assert dict(parse_qsl(urlsplit(page.url).query))['household'] == second_house.pk
                page.reload()
                expect(page.get_by_label('家庭', exact=True)).to_have_value(second_house.pk)
                page.goto(origin + app_url(f'/ai/config/{house.pk}/', household=second_house.pk))
                expect(page.get_by_label('家庭', exact=True)).to_have_value(house.pk)
                expect(page.locator('.workspace-page')).to_be_visible()
                page.screenshot(path=str(output / 'household-path-context.png'), full_page=True)
                checks.append('household-path-navigation-and-direct-restore')
                # A real forwarded HTML form, including browser validation and the
                # original hidden request/context tokens, must work through React.
                page.goto(origin + app_url('/prints/arithmetic/'))
                expect(page.locator('.workspace-page')).to_be_visible()
                page.locator('input[name=expression]').fill('4*2')
                page.get_by_role('button', name='复算', exact=True).click()
                expect(page.locator('.workspace-page')).to_contain_text('8')
                assert page.evaluate('window.location.pathname') == '/app/'
                checks.append('server-form-post-stays-in-shell')
                # Business links, original images and source widgets are exercised
                # separately from the GET matrix so success is not inferred from 200.
                page.goto(origin + app_url(f'/knowledge/entity/{f["node"]}/'))
                expect(page.locator('.workspace-page')).to_be_visible()
                page.locator(f'.workspace-page a[href^="/knowledge/question/{f["question_entity"]}/"]').first.click()
                expect(page.locator('.workspace-page h1')).to_contain_text('题')
                assert '/app/' in page.url
                checks.append('knowledge-question-bidirectional-source-links')
                # Source selection uses the allowlisted native widget in the
                # React frame, including a rotated preview and cross-page state.
                page.goto(origin + app_url(f'/page/{f["page"]}/'))
                expect(page.locator('.region-canvas')).to_be_visible()
                page.locator('.rotation-select').select_option('90')
                expect(page.locator('.region-card')).to_have_attribute('data-rotation', '90')
                for field, value in [('x0','2'), ('y0','2'), ('x1','22'), ('y1','28')]:
                    page.locator('.coord-' + field).fill(value)
                page.get_by_role('button', name='加入坐标区域', exact=True).click()
                expect(page.locator('.selected-source-list li')).to_have_count(1)
                # Rotation is a view control, not an unsaved business edit.
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('link', name='用所选区域录入题目', exact=True).click()
                expect(page.locator('.workspace-page h1')).to_contain_text('题目')
                expect(page.locator('.selected-source-list li')).to_have_count(1)
                checks.append('source-rotation-selection-transfer')
                page.goto(origin + app_url(f'/page/{f["page"]}/'))
                page.locator('.workspace-page a[href^="/derivative/"]').first.click()
                expect(page.get_by_role('dialog')).to_be_visible()
                assert urlsplit(page.url).path == '/app/'
                page.get_by_role('button', name='关闭预览', exact=True).click()
                checks.append('private-image-preview-in-frame')
                page.goto(origin + app_url(f'/prints/snapshots/{f["snapshots"][1]}/'))
                with page.expect_response(lambda r: '/document.pdf/' in r.url and 'preview=1' in r.url) as pdf_preview:
                    page.get_by_role('link', name='预览 PDF', exact=True).click()
                assert pdf_preview.value.status == 200
                assert 'inline' in pdf_preview.value.headers.get('content-disposition', '')
                expect(page.get_by_role('dialog').locator('iframe')).to_be_visible()
                assert urlsplit(page.url).path == '/app/'
                page.get_by_role('button', name='关闭预览', exact=True).click()
                with page.expect_download() as native_word:
                    page.get_by_role('link', name='下载 Word', exact=True).click()
                assert native_word.value.suggested_filename == 'document.docx'
                checks.append('native-pdf-inline-preview-and-word-download')
                # Editing preserves the original attempt and appends a revision.
                from app.persistence.models import EntityRecord
                attempt_entity = db(lambda: EntityRecord.objects.get(kind='attempt', stable_id=f['attempt']))
                original_head = attempt_entity.head_revision_id
                attempt_count = db(lambda: EntityRecord.objects.filter(household_id=house.pk, kind='attempt').count())
                page.goto(origin + app_url(f'/learning/attempt/{f["attempt"]}/edit/'))
                page.locator('#id_answer_text').fill('8 · 合成修订')
                page.locator('#id_reason').fill('PC 同框追加修订验收')
                page.locator('.workspace-page form button[type=submit]').click()
                expect(page.locator('.workspace-page h1')).to_contain_text('4 × 2')
                expect(page.locator('.workspace-page')).to_contain_text('8 · 合成修订')
                assert db(lambda: EntityRecord.objects.filter(household_id=house.pk, kind='attempt').count()) == attempt_count
                assert db(lambda: EntityRecord.objects.get(pk=attempt_entity.pk).head_revision_id) != original_head
                checks.append('attempt-edit-appends-history')
                # The import review must display the exact pending teaching PNG
                # and readable formulas before any confirmation writes records.
                page.goto(origin + app_url(view='materials'))
                page.get_by_role('button', name=re.compile('合成容器验收 PC 资料')).click()
                expect(page.get_by_label('选择多张原图')).to_be_visible()
                expect(page.locator(f'img[src^="/api/v1/workflows/{pending.pk}/assets/"]')).to_be_visible()
                expect(page.get_by_label(re.compile('^公式 ')).first).to_be_visible()
                assert page.request.get(origin + f'/api/v1/workflows/{pending.pk}/').json()['job']['state'] == 'needs_review'
                page.screenshot(path=str(output / 'import-png-review.png'), full_page=True)
                checks.append('pending-import-teaching-png-visible')
                # A dropped response for one item must leave only that item for
                # retry. Successful uploads and their idempotence keys survive.
                upload_count = db(lambda: material.pages.count())
                upload_target = f'**/api/v1/materials/{material.pk}/upload/'
                upload_seen = []
                def interrupt_one(route):
                    upload_seen.append(route.request.method)
                    if len(upload_seen) == 2: route.abort('failed')
                    else: route.continue_()
                context.route(upload_target, interrupt_one)
                files = []
                for name, color in [('pc-a.png','red'), ('pc-b.png','blue')]:
                    buf = BytesIO(); Image.new('RGB', (80,60), color).save(buf, format='PNG')
                    files.append({'name':name, 'mimeType':'image/png', 'buffer':buf.getvalue()})
                page.get_by_label('选择多张原图').set_input_files(files)
                page.get_by_role('button', name='上传待处理原图（2）', exact=True).click()
                expect(page.get_by_text('失败 1 张', exact=True)).to_be_visible()
                assert db(lambda: material.pages.count()) == upload_count + 1
                page.get_by_role('button', name='重试此图', exact=True).click()
                expect(page.get_by_text('已完成 2 张', exact=True)).to_be_visible()
                assert db(lambda: material.pages.count()) == upload_count + 2
                assert len(upload_seen) == 3
                context.unroute(upload_target, interrupt_one)
                checks.append('multi-upload-single-failure-retry-without-duplicate')
                transparent_page = db(lambda: materials.upload_page(actor, material.pk,
                    SimpleUploadedFile('transparent.png', transparent.getvalue(), content_type='image/png'), uuid4().hex))
                # The native editor saves automatically, compares immutable
                # history, and queues a real deterministic worker with AI off.
                page.get_by_role('button', name='整理解析', exact=True).click()
                expect(page.get_by_role('heading', level=1, name=re.compile('逐题解析'))).to_be_visible()
                page.get_by_label('选择资料页').select_option(transparent_page['page_id'])
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST') as source_saved:
                    page.get_by_role('button', name='加入整页来源（范围未知）', exact=True).click()
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_have_text(f'已保存为版本 {source_saved.value.json()["revision"]["version"]}。')
                page.get_by_label('图片类型').select_option('source_image')
                page.get_by_label('对应原图来源').select_option('1')
                page.get_by_label('图示名称', exact=True).fill('透明原图来源')
                page.get_by_label('依据', exact=True).fill('按合成透明原图取出，验证丢响应重试')
                asset_count = db(lambda: material.solution_assets.count())
                source_keys = []
                derive_target = f'**/api/v1/materials/{material.pk}/solutions/source-assets/'
                def lose_asset_response(route):
                    source_keys.append(route.request.post_data_json['request_key'])
                    if len(source_keys) == 1:
                        response = route.fetch()
                        assert response.status == 200
                        route.abort('failed')
                    else:
                        route.continue_()
                context.route(derive_target, lose_asset_response)
                page.get_by_role('button', name='上传素材', exact=True).click()
                expect(page.get_by_role('alert')).to_be_visible()
                assert db(lambda: material.solution_assets.count()) == asset_count + 1
                page.get_by_role('button', name='上传素材', exact=True).click()
                expect(page.get_by_text('图示已收存，可在图示列表中选择。', exact=True)).to_be_visible()
                assert source_keys[0] == source_keys[1]
                assert db(lambda: material.solution_assets.count()) == asset_count + 1
                context.unroute(derive_target, lose_asset_response)
                from app.solutions.models import SolutionAsset
                derived = db(lambda: SolutionAsset.objects.get(request_key=source_keys[0]))
                with Image.open(materials.asset_path(derived.storage_key, derived.sha256)) as image:
                    assert image.convert('RGBA').getpixel((0, 0)) == (30, 60, 120, 128)
                checks.append('transparent-source-asset-lost-response-retry-without-duplicate')
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST') as saved:
                    page.get_by_label('文档标题', exact=True).fill('PC 浏览器保存的解析')
                assert saved.value.status == 200
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_have_text(f'已保存为版本 {saved.value.json()["revision"]["version"]}。')
                page.get_by_role('button', name='打开并对照', exact=True).last.click()
                expect(page.get_by_text('历史版本对照', exact=True)).to_be_visible()
                assert not re.search(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b', page.locator('main').inner_text())
                page.get_by_role('button', name='关闭', exact=True).click()
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST') as formula_saved:
                    page.get_by_label('公式 1', exact=True).fill('4*2+1/2-1/2')
                    expect(page.get_by_label('公式 1 预览', exact=True)).to_be_visible()
                assert formula_saved.value.status == 200
                generated_version = formula_saved.value.json()['revision']['version']
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_have_text(f'已保存为版本 {generated_version}。')
                page.get_by_role('button', name='生成 PDF / Word', exact=True).click()
                expect(page.get_by_text('等待生成', exact=False)).to_be_visible()
                from app.solutions import jobs as solution_jobs
                rendered = db(solution_jobs.execute_next)
                assert rendered is not None and rendered.state == 'output_check', getattr(rendered, 'error_code', '')
                ready_output = page.locator('article').filter(has=page.get_by_role('heading', name=f'可预览，待检查 · 版本 {generated_version}', exact=True))
                expect(ready_output).to_be_visible(timeout=20000)
                ready_output.get_by_role('button', name='查看输出', exact=True).click()
                expect(page.locator('iframe[title$="PDF 预览"]')).to_have_count(6, timeout=20000)
                # Existing output and newly generated output are both retained.
                settle_visuals()
                page.screenshot(path=str(output / 'solution-editor-output.png'), full_page=True)
                checks.append('editor-autosave-history-real-worker-preview')
                page.reload()
                expect(page.get_by_label('文档标题', exact=True)).to_have_value('PC 浏览器保存的解析')
                checks.append('editor-refresh-restores-saved-draft')
                word_only = {'per_question': ['docx'], 'per_lecture': ['docx'], 'combined': ['docx']}
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST'
                    and r.request.post_data_json['content']['outputs'] == word_only) as word_saved:
                    for organization in ('逐题文档', '按讲次合并', '整份合并'):
                        page.get_by_role('group', name=organization, exact=True).get_by_label('PDF', exact=True).uncheck()
                word_version = word_saved.value.json()['revision']['version']
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_have_text(f'已保存为版本 {word_version}。')
                page.get_by_role('button', name='生成 PDF / Word', exact=True).click()
                expect(page.get_by_text('等待生成', exact=False)).to_be_visible()
                word_rendered = db(solution_jobs.execute_next)
                assert word_rendered.state == 'output_check', word_rendered.error_code
                word_card = page.locator('article').filter(has=page.get_by_role('heading', name=f'可预览，待检查 · 版本 {word_version}', exact=True))
                expect(word_card).to_be_visible(timeout=20000)
                word_card.get_by_role('button', name='查看输出', exact=True).click()
                expect(word_card.locator('img[alt$="页预览"]')).to_have_count(5)
                assert word_card.locator('iframe').count() == 0
                assert word_card.get_by_role('link', name='下载 Word', exact=True).count() == 3
                settle_visuals()
                word_card.screenshot(path=str(output / 'word-only-output-previews.png'))
                checks.append('word-only-every-page-preview-without-pdf-download')
                # Empty family and viewer boundaries use actual sessions.
                page.goto(origin + app_url(view='materials', household=second_house.pk))
                expect(page.get_by_label('家庭', exact=True)).to_have_value(second_house.pk)
                page.screenshot(path=str(output / 'empty-household.png'), full_page=True)
                checks.append('empty-second-household-context')
                context.clear_cookies(); login(viewer)
                page.goto(origin + app_url('/knowledge/?household_id=' + house.pk))
                expect(page.locator('.workspace-page')).to_be_visible()
                assert not page.locator('.workspace-page a[href*="/knowledge/create/"]').count()
                denied = page.request.get(origin + '/api/v1/workspace/page/?' + urlencode({'url':f'/ai/config/{house.pk}/'}))
                assert denied.status == 404  # Owner-only configuration stays private.
                csrf = page.request.get(origin + '/api/v1/session/').json()['csrf_token']
                denied_post = page.request.post(origin + '/api/v1/materials/' + str(material.pk) + '/solutions/draft/',
                    data={'content':{}, 'expected_version':1, 'request_key':uuid4().hex, 'reason':'只读拒绝'},
                    headers={'X-CSRFToken':csrf})
                assert denied_post.status == 404  # Permission denials do not reveal private records.
                checks.append('viewer-read-only-mutation-denied')
                context.clear_cookies()
                page.get_by_role('navigation', name='主导航').get_by_role('button', name='设置', exact=True).click()
                expect(page.get_by_role('link', name='前往登录', exact=True)).to_be_visible()
                page.get_by_role('link', name='前往登录', exact=True).click()
                page.wait_for_url(lambda url: urlsplit(url).path == '/accounts/login/')
                expect(page.locator('#id_username')).to_be_visible()
                checks.append('expired-session-login')
                assert not errors, errors
                assert not external, external
                assert not leaks, leaks
                browser.close()
    finally:
        if server:
            server.terminate()
            try: server.wait(timeout=10)
            except subprocess.TimeoutExpired: server.kill(); server.wait()
        pool.shutdown(wait=True)
        report = {'checks':checks, 'matrix':matrix, 'template_coverage':sorted(expected_templates),
                  'errors':errors, 'external':external, 'leaks':leaks}
        (output / 'verification.local.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        for path in output.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)
    print(json.dumps({'checks':len(checks), 'pages':len(matrix), 'report':str(output / 'verification.local.json')}, ensure_ascii=False))


if __name__ == '__main__': main()
