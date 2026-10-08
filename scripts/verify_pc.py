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
    checks, matrix, errors, external, leaks, ux_measurements, theme_contrast, row_measurements = [], [], [], [], [], [], [], []
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
                browser = pw.chromium.launch(headless=os.environ.get('SWB_PC_HEADED') != '1', channel='chromium')
                context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True)
                def restrict(route):
                    # Chromium's bundled PDF viewer reads local browser assets;
                    # these schemes make no external HTTP request. Keep network
                    # access restricted to this owned application origin.
                    local_pdf = route.request.url.startswith((
                        'chrome-extension://mhjfbmdgcfjbbpaeojofohoefgiehjai/',
                        'chrome://resources/'))
                    if route.request.url.startswith(origin + '/') or local_pdf: route.continue_()
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
                        await Promise.allSettled(document.getAnimations()
                            .filter(animation => animation.effect.getComputedTiming().iterations !== Infinity)
                            .map(animation => animation.finished));
                    }''')
                def open_disclosure(label, scope=None):
                    summary = (scope or page).locator('summary').filter(has_text=re.compile('^' + re.escape(label)))
                    expect(summary).to_have_count(1)
                    if not summary.evaluate('(element) => element.parentElement.open'):
                        summary.click()

                def check_business_text(scope, label):
                    visible = scope.inner_text()
                    codes = re.findall(r'\b(?:swb\.[a-z0-9.-]+|schema_version|request_key|source_stamp|base_stamp|sha-?256|[a-z][a-z0-9]*_[a-z0-9_]+|[0-9a-f]{64}|[0-9a-f]{8}-[0-9a-f-]{27,})\b', visible, re.I)
                    assert not codes, (label, codes)

                def check_text_contrast(view, theme):
                    samples = page.evaluate('''() => {
                        const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
                        const ctx = canvas.getContext('2d');
                        const color = value => {
                            ctx.clearRect(0, 0, 1, 1); ctx.fillStyle = value; ctx.fillRect(0, 0, 1, 1);
                            return [...ctx.getImageData(0, 0, 1, 1).data].map(v => v / 255);
                        };
                        const blend = (top, bottom) => top.slice(0, 3).map((v, i) => v * top[3] + bottom[i] * (1 - top[3]));
                        const luminance = rgb => rgb.map(v => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
                            .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
                        return [...document.querySelectorAll('#content h1, #content h2, #content p, #content button, #content label, #content th, #content td, #content [role="status"] span, nav[aria-label="主导航"] button')]
                            .filter(el => {
                                if (!el.getClientRects().length || !el.textContent.trim() || el.disabled) return false;
                                for (let parent = el.parentElement; parent; parent = parent.parentElement) {
                                    if (parent.tagName === 'DETAILS' && !parent.open && !parent.querySelector(':scope > summary')?.contains(el)) return false;
                                }
                                return getComputedStyle(el).visibility !== 'hidden';
                            })
                            .slice(0, 100).map(el => {
                                const ancestors = []; for (let node = el; node; node = node.parentElement) ancestors.unshift(node);
                                const background = ancestors.reduce((bg, node) => blend(color(getComputedStyle(node).backgroundColor), bg), [1, 1, 1]);
                                const style = getComputedStyle(el), foreground = blend(color(style.color), background);
                                const lights = [luminance(foreground), luminance(background)].sort((a, b) => b - a);
                                const size = parseFloat(style.fontSize), large = size >= 24 || (size >= 18.66 && parseInt(style.fontWeight) >= 700);
                                return {text: el.textContent.trim().slice(0, 60), ratio: (lights[0] + .05) / (lights[1] + .05), minimum: large ? 3 : 4.5};
                            });
                    }''')
                    assert samples, (view, theme)
                    failed = [sample for sample in samples if sample['ratio'] + .02 < sample['minimum']]
                    assert not failed, (view, theme, failed)
                    theme_contrast.append({'view':view, 'theme':theme, 'samples':samples})

                page.goto(origin + app_url(view='overview') + '&learner=' + f['learner'])
                expect(page.get_by_role('heading', name='今天从哪里开始？')).to_be_visible()
                use_mode = page.get_by_role('group', name='使用方式', exact=True)
                expect(use_mode.get_by_role('button', name='学生练习', exact=True)).to_have_attribute('aria-pressed', 'true')
                expect(use_mode.get_by_role('button', name='家长跟进', exact=True)).to_have_attribute('aria-pressed', 'false')
                parent_summary = page.locator('summary').filter(has_text=re.compile('^家长整理与记录$'))
                expect(parent_summary).to_be_visible()
                assert not parent_summary.evaluate('(element) => element.parentElement.open')
                record_attempt = page.get_by_role('button', name='记录一次作答', exact=True)
                expect(record_attempt).not_to_be_visible()
                help_button = page.get_by_role('button', name='学习顺序帮助', exact=True)
                help_button.focus()
                expect(page.get_by_role('tooltip')).to_be_visible()
                help_button.press('Escape')
                expect(page.get_by_role('tooltip')).to_have_count(0)
                parent_summary.click()
                expect(record_attempt).to_be_visible()
                record_attempt.click()
                expect(page.locator('.workspace-page h1')).to_contain_text('作答')
                checks.append('overview-default-student-mode-parent-actions-collapsed-until-open')
                for action_name, view in [('选题练习', 'knowledge'), ('查看讲解', 'documents'), ('复习安排', 'progress')]:
                    page.goto(origin + app_url(view='overview') + '&learner=' + f['learner'])
                    page.get_by_role('button', name=action_name, exact=True).click()
                    page.wait_for_url(lambda url: dict(parse_qsl(urlsplit(url).query)).get('view') == view)
                    if action_name == '选题练习':
                        expect(page.locator('#question-index')).to_be_in_viewport()
                touch_context = browser.new_context(viewport={'width':390, 'height':844}, has_touch=True, storage_state=context.storage_state())
                touch_context.route('**/*', restrict)
                phone = touch_context.new_page()
                phone.on('pageerror', lambda error: errors.append(str(error)))
                phone.goto(origin + app_url(view='overview') + '&learner=' + f['learner'])
                expect(phone.get_by_role('heading', name='今天从哪里开始？')).to_be_visible()
                phone.get_by_role('button', name='学习顺序帮助', exact=True).tap()
                expect(phone.get_by_role('tooltip')).to_be_visible()
                bounds = phone.get_by_role('tooltip').bounding_box()
                assert bounds and 0 <= bounds['x'] and bounds['x'] + bounds['width'] <= 390
                assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                phone.screenshot(path=str(output / 'student-home-390-tooltip.png'), full_page=True)
                touch_context.close()
                page.goto(origin + app_url(view='overview') + '&learner=' + f['learner'])
                expect(page.get_by_role('heading', name='今天从哪里开始？')).to_be_visible()
                settle_visuals()
                page.screenshot(path=str(output / 'student-home-1440.png'), full_page=True)
                checks.append('student-and-family-start-actions-keyboard-and-touch-help')
                for name, path in paths:
                    with page.expect_response(lambda r: '/api/v1/workspace/page/' in r.url) as fetched:
                        page.goto(origin + app_url(path))
                    response = fetched.value
                    assert response.status == 200, (name, response.status, response.text()[:300])
                    assert target_key(response.json()['page']['url']) == target_key(path), name
                    expect(page.locator('.workspace-page')).to_have_count(1)
                    if name == 'prints':
                        recent_tab = page.get_by_role('tab', name='最近成果', exact=True)
                        expect(recent_tab).to_have_attribute('aria-selected', 'true')
                        expect(page.get_by_role('region', name='最近成果', exact=True)).to_be_visible()
                        expect(page.get_by_role('tabpanel', name='家长解析', exact=True)).not_to_be_visible()
                        expect(page.locator('.workspace-page')).not_to_be_visible()
                        page.screenshot(path=str(output / 'document-home-default.png'), full_page=True)
                        page.get_by_role('tab', name='家长解析', exact=True).click()
                        expect(page.get_by_role('tab', name='家长解析', exact=True)).to_have_attribute('aria-selected', 'true')
                        expect(page.get_by_role('tabpanel', name='家长解析', exact=True)).to_be_visible()
                        checks.append('document-center-default-recent-explicit-parent-tab')
                    else:
                        expect(page.locator('.workspace-page')).to_be_visible()
                    expect(page.get_by_role('navigation', name='主导航')).to_be_visible()
                    if name != 'prints':
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
                # Keep a real headed-browser rendering for visual inspection;
                # HTTP success and the iframe alone are not a PDF visual pass.
                page.wait_for_timeout(10000)
                pdf_frames = [frame for frame in page.frames if frame.url.startswith('chrome-extension://') and frame.locator('pdf-viewer').count()]
                assert pdf_frames, 'Native PDF viewer did not load'
                expect(pdf_frames[0].locator('viewer-toolbar')).to_be_visible()
                page.screenshot(path=str(output / 'native-pdf-rendered.png'), full_page=True)
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
                page.goto(origin + app_url(f'/learning/attempt/{f["attempt"]}/edit/', household=second_house.pk) + '&learner=' + second_learner)
                expect(page.get_by_label('家庭', exact=True)).to_have_value(house.pk)
                expect(page.get_by_label('学习者', exact=True)).to_have_value(f['learner'])
                with page.expect_response(lambda r: '/draft-save/' in r.url and r.request.method == 'POST') as form_draft:
                    page.locator('#id_answer_text').fill('8 · 合成修订')
                assert form_draft.value.status == 200
                assert db(lambda: EntityRecord.objects.get(pk=attempt_entity.pk).head_revision_id) == original_head
                draft_fields = [field for form in form_draft.value.json()['draft']['payload']['forms'] for field in form['fields']]
                assert not any(field['kind'] in ('hidden', 'password', 'file') for field in draft_fields)
                assert dict(parse_qsl(urlsplit(form_draft.value.url).query))['household'] == str(house.pk)
                page.reload()
                expect(page.get_by_text('发现一份未完成的表单草稿', exact=True)).to_be_visible()
                assert page.locator('#id_answer_text').input_value() != '8 · 合成修订'
                assert not re.search(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b', page.get_by_role('region', name='私人草稿', exact=True).inner_text())
                page.screenshot(path=str(output / 'form-draft-recovery.png'), full_page=True)
                page.get_by_role('button', name='恢复这份草稿', exact=True).click()
                expect(page.locator('#id_answer_text')).to_have_value('8 · 合成修订')
                page.locator('#id_reason').fill('PC 同框追加修订验收')
                page.locator('.workspace-page form button[type=submit]').click()
                expect(page.locator('.workspace-page h1')).to_contain_text('4 × 2')
                expect(page.locator('.workspace-page')).to_contain_text('8 · 合成修订')
                assert db(lambda: EntityRecord.objects.filter(household_id=house.pk, kind='attempt').count()) == attempt_count
                assert db(lambda: EntityRecord.objects.get(pk=attempt_entity.pk).head_revision_id) != original_head
                checks.append('private-form-recovery-authoritative-family-and-explicit-append-history')
                # The import review must display the exact pending teaching PNG
                # and readable formulas before any confirmation writes records.
                page.goto(origin + app_url(view='materials'))
                page.get_by_role('button', name=re.compile('合成容器验收 PC 资料')).click()
                page.get_by_role('tab', name=re.compile('^原图与进度')).click()
                page.get_by_text('添加原图照片', exact=True).click()
                expect(page.get_by_label('选择多张原图')).to_be_visible()
                page.get_by_role('tab', name=re.compile('^整理任务')).click()
                expect(page.locator(f'img[src^="/api/v1/workflows/{pending.pk}/assets/"]')).to_be_visible()
                expect(page.get_by_label(re.compile('^公式 ')).first).to_be_visible()
                assert page.request.get(origin + f'/api/v1/workflows/{pending.pk}/').json()['job']['state'] == 'needs_review'
                page.screenshot(path=str(output / 'import-png-review.png'), full_page=True)
                checks.append('pending-import-teaching-png-visible')
                import_picker = page.get_by_label('选择导入文件（.json）', exact=True)
                job_count = db(lambda: type(pending).objects.count())
                import_picker.set_input_files({'name':'invalid-import.json', 'mimeType':'application/json',
                    'buffer':b'{"schema_version":"swb.skill-import.v1","schema_version":"swb.skill-import.v1"}'})
                expect(page.get_by_text(re.compile('导入文件中有重复信息'))).to_be_visible()
                check_business_text(page.locator('#content'), 'import-rejected-file')
                preview_proposal = json.loads(json.dumps(proposal))
                preview_proposal['tool_inputs'] = {'context':'synthetic local preview only'}
                import_picker.set_input_files({'name':'valid-import.json', 'mimeType':'application/json',
                    'buffer':json.dumps(preview_proposal).encode()})
                expect(page.get_by_text('文件已读取', exact=True)).to_be_visible()
                expect(page.get_by_text('补充信息（待核对）', exact=True)).to_be_visible()
                expect(page.get_by_text('另有内容待核对，已保留。', exact=True).first).to_be_visible()
                check_business_text(page.locator('#content'), 'import-preview')
                assert db(lambda: type(pending).objects.count()) == job_count
                settle_visuals()
                page.screenshot(path=str(output / 'import-local-preview.png'), full_page=True)
                page.get_by_role('button', name='移除此文件', exact=True).click()
                expect(page.get_by_text('文件已读取', exact=True)).not_to_be_visible()
                expect(page.get_by_text('私人草稿已保存。', exact=True)).to_be_visible()
                checks.append('import-local-preview-strict-rejection-unknown-content-and-business-copy')
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
                page.get_by_role('tab', name=re.compile('^原图与进度')).click()
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
                page.get_by_role('tab', name=re.compile('^题面核对')).click()
                printed_input = page.get_by_role('textbox', name='图中印刷题面转写（必填）', exact=True)
                expect(printed_input).to_be_visible()
                original_printed = printed_input.input_value()
                assert original_printed, 'continue must open an existing unfinished question'
                original_question = page.get_by_role('combobox', name='正在核对的题目', exact=True).input_value()
                assert original_question
                pending = page.locator('section[aria-labelledby="content-question-readiness-title"]')
                confirmation_gap = pending.get_by_role('listitem').filter(has_text='待补：人工核对与确认')
                confirmation_gap.get_by_role('button', name='去补充：人工核对与确认', exact=True).click()
                expect(page.locator('#content-question-confirmation')).to_be_focused()
                expect(page.locator('#content-question-confirmation')).not_to_be_checked()
                page.wait_for_function('''() => {
                    const rect = document.querySelector('#content-question-confirmation').getBoundingClientRect();
                    return rect.top >= 80 && rect.bottom <= innerHeight;
                }''')
                page.locator('#content-question-confirmation').scroll_into_view_if_needed()
                settle_visuals()
                page.screenshot(path=str(output / 'materials-content-focused-confirmation.png'))
                page.evaluate("window.scrollTo({top: 0, behavior: 'instant'})")
                settle_visuals()
                check_text_contrast('materials-content-pending', 'light')
                page.screenshot(path=str(output / 'materials-content-pending-light.png'), full_page=True)
                page.evaluate("document.documentElement.classList.add('dark')")
                settle_visuals()
                check_text_contrast('materials-content-pending', 'dark')
                page.screenshot(path=str(output / 'materials-content-pending-dark.png'), full_page=True)
                page.evaluate("document.documentElement.classList.remove('dark')")
                checks.append('continued-question-real-confirmation-field-focus-and-light-dark-pending-content')
                printed_input.fill('浏览器临时输入：切标签和取消刷新仍应保留')
                page.get_by_role('tab', name=re.compile('^整理任务')).click()
                page.get_by_role('tab', name=re.compile('^题面核对')).click()
                (output / 'content-tab-state.local.json').write_text(json.dumps({
                    'url': page.url,
                    'content_inputs': printed_input.count(),
                    'panels': page.locator('[role=tabpanel]').evaluate_all('(panels) => panels.map(panel => ({id:panel.id, hidden:panel.hidden, children:panel.childElementCount}))'),
                    'visible_text': page.locator('#content').inner_text(),
                }, ensure_ascii=False, indent=2) + '\n')
                page.screenshot(path=str(output / 'content-tab-restoration.png'), full_page=True)
                expect(printed_input).to_have_value('浏览器临时输入：切标签和取消刷新仍应保留')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button', name='刷新核对数据', exact=True).click()
                expect(printed_input).to_have_value('浏览器临时输入：切标签和取消刷新仍应保留')
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='刷新核对数据', exact=True).click()
                expect(printed_input).to_have_value(original_printed)
                expect(page.get_by_role('combobox', name='正在核对的题目', exact=True)).to_have_value(original_question)
                page.get_by_role('button', name='＋ 新建题目草稿', exact=True).click()
                expect(printed_input).to_have_value('')
                page.get_by_role('tab', name='整页阅读', exact=True).click()
                reading_input = page.get_by_role('textbox', name='阅读依据（必填）', exact=True)
                expect(reading_input).to_be_visible()
                reading_input.fill('浏览器临时阅读依据：切来源页须确认')
                source_picker = page.get_by_role('combobox', name='来源页', exact=True)
                expect(source_picker.locator('option')).to_have_count(upload_count + 2)
                initial_source = source_picker.input_value()
                alternate_source = source_picker.locator('option').evaluate_all('(options, current) => options.map(option => option.value).find(value => value !== current)', initial_source)
                assert alternate_source
                page.once('dialog', lambda dialog: dialog.dismiss())
                source_picker.select_option(alternate_source)
                expect(source_picker).to_have_value(initial_source)
                expect(reading_input).to_have_value('浏览器临时阅读依据：切来源页须确认')
                page.once('dialog', lambda dialog: dialog.accept())
                source_picker.select_option(alternate_source)
                expect(source_picker).to_have_value(alternate_source)
                expect(reading_input).not_to_have_value('浏览器临时阅读依据：切来源页须确认')
                source_picker.select_option(initial_source)
                expect(reading_input).to_be_visible()
                checks.append('content-tabs-and-confirmed-refresh-source-page-input-protection')
                transparent_page = db(lambda: materials.upload_page(actor, material.pk,
                    SimpleUploadedFile('transparent.png', transparent.getvalue(), content_type='image/png'), uuid4().hex))
                # Automatic recovery is private; only explicit saving appends
                # formal history. Queue a real deterministic worker with AI off.
                from app.solutions.models import SolutionRevision, SolutionOutput
                from app.workflows.models import WorkspaceDraft
                initial_versions = db(lambda: SolutionRevision.objects.filter(material=material).count())
                page.get_by_role('tab', name='讲解', exact=True).click()
                navigation_dialogs = []
                def accept_temporary_input_navigation(dialog):
                    navigation_dialogs.append(dialog.message)
                    assert dialog.message == '页面有未保存的更改。确定离开当前页面吗？'
                    dialog.accept()
                page.on('dialog', accept_temporary_input_navigation)
                try:
                    page.get_by_role('button', name='打开讲解工作区', exact=True).click()
                    expect(page.get_by_role('heading', level=1, name='逐题讲解')).to_be_visible()
                finally:
                    page.remove_listener('dialog', accept_temporary_input_navigation)
                    (output / 'solution-entry-state.local.json').write_text(json.dumps({
                        'url':page.url, 'dialogs':navigation_dialogs,
                        'headings':page.get_by_role('heading').all_text_contents(),
                        'visible_text':page.locator('#content').inner_text(),
                    }, ensure_ascii=False, indent=2) + '\n')
                    page.screenshot(path=str(output / 'solution-entry.png'), full_page=True)
                page.get_by_label('选择资料页').select_option(transparent_page['page_id'])
                with page.expect_response(lambda r: '/draft-save/' in r.url and r.request.method == 'POST') as source_saved:
                    page.get_by_role('button', name='加入整页来源（范围未知）', exact=True).click()
                assert source_saved.value.status == 200
                assert db(lambda: SolutionRevision.objects.filter(material=material).count()) == initial_versions
                page.get_by_text('知识关联、题面图示、订正与素材', exact=True).click()
                page.get_by_label('图片类型').select_option('source_image')
                page.get_by_label('对应原图来源').select_option(json.dumps([transparent_page['page_id'], None], separators=(',', ':')))
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
                expect(page.get_by_text('素材已加入本资料素材库；它没有自动关联步骤，请在需要的位置选择。', exact=True)).to_be_visible()
                assert source_keys[0] == source_keys[1]
                assert db(lambda: material.solution_assets.count()) == asset_count + 1
                context.unroute(derive_target, lose_asset_response)
                from app.solutions.models import SolutionAsset
                derived = db(lambda: SolutionAsset.objects.get(request_key=source_keys[0]))
                with Image.open(materials.asset_path(derived.storage_key, derived.sha256)) as image:
                    assert image.convert('RGBA').getpixel((0, 0)) == (30, 60, 120, 128)
                checks.append('transparent-source-asset-lost-response-retry-without-duplicate')
                open_disclosure('文档设置')
                with page.expect_response(lambda r: '/draft-save/' in r.url and r.request.method == 'POST') as saved:
                    page.get_by_label('文档标题', exact=True).fill('PC 浏览器保存的解析')
                assert saved.value.status == 200
                assert db(lambda: SolutionRevision.objects.filter(material=material).count()) == initial_versions
                draft_key = saved.value.json()['draft']['key']
                page.reload()
                expect(page.get_by_text('发现未处理的私人草稿', exact=True)).to_be_visible()
                page.get_by_role('button', name='比较内容', exact=True).click()
                expect(page.get_by_text('私人草稿比较', exact=True)).to_be_visible()
                assert not re.search(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b', page.locator('main').inner_text())
                page.get_by_role('button', name='关闭比较', exact=True).click()
                page.get_by_role('button', name='恢复私人草稿', exact=True).click()
                open_disclosure('文档设置')
                expect(page.get_by_label('文档标题', exact=True)).to_have_value('PC 浏览器保存的解析')
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST') as formal_saved:
                    page.get_by_role('button', name='保存为新版本', exact=True).click()
                assert formal_saved.value.status == 200
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_contain_text(f'已保存为版本 {formal_saved.value.json()["revision"]["version"]}。')
                assert db(lambda: SolutionRevision.objects.filter(material=material).count()) == initial_versions + 1
                expect(page.get_by_text('私人草稿已清理。', exact=True)).to_be_visible()
                assert db(lambda: WorkspaceDraft.objects.get(actor=actor, household=house, key=draft_key).payload) == {'cleared': True}
                checks.append('private-autosave-compare-reload-explicit-version-and-tombstone')
                page.get_by_role('tab', name=re.compile('^历史版本')).click()
                page.get_by_role('button', name='打开并对照', exact=True).last.click()
                expect(page.get_by_text('历史版本对照', exact=True)).to_be_visible()
                assert not re.search(r'\b[0-9a-f]{8}-[0-9a-f-]{27,}\b', page.locator('main').inner_text())
                page.get_by_role('button', name='关闭', exact=True).click()
                page.get_by_role('tab', name='编辑讲解', exact=True).click()
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST') as formula_saved:
                    page.get_by_label('第 1 步公式表达式', exact=True).fill('4*2+1/2-1/2')
                    expect(page.get_by_label('第 1 步公式预览', exact=True)).to_be_visible()
                    page.get_by_role('button', name='保存为新版本', exact=True).click()
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
                if ready_output.get_by_role('button', name='查看输出', exact=True).count():
                    ready_output.get_by_role('button', name='查看输出', exact=True).click()
                expect(ready_output.locator('iframe[title$="PDF 预览"]')).to_have_count(3, timeout=20000)
                assert db(lambda: SolutionOutput.objects.filter(revision__material=material).count()) == 3
                # Existing output and newly generated output are both retained.
                settle_visuals()
                page.screenshot(path=str(output / 'solution-editor-output.png'), full_page=True)
                checks.append('editor-structured-step-history-real-worker-preview')
                page.reload()
                page.get_by_role('tab', name='编辑讲解', exact=True).click()
                open_disclosure('文档设置')
                expect(page.get_by_label('文档标题', exact=True)).to_have_value('PC 浏览器保存的解析')
                checks.append('editor-refresh-restores-saved-draft')
                open_disclosure('文档设置')
                word_only = {'per_question': ['docx'], 'per_lecture': ['docx'], 'combined': ['docx']}
                with page.expect_response(lambda r: '/solutions/draft/' in r.url and r.request.method == 'POST'
                    and r.request.post_data_json['content']['outputs'] == word_only) as word_saved:
                    for organization in ('逐题文档', '按讲次合并', '整份合并'):
                        page.get_by_role('group', name=organization, exact=True).get_by_label('PDF', exact=True).uncheck()
                    page.get_by_role('button', name='保存为新版本', exact=True).click()
                word_version = word_saved.value.json()['revision']['version']
                expect(page.get_by_role('status').filter(has_text='已保存为版本')).to_have_text(f'已保存为版本 {word_version}。')
                page.get_by_role('button', name='生成 Word', exact=True).click()
                expect(page.get_by_text('等待生成', exact=False)).to_be_visible()
                word_rendered = db(solution_jobs.execute_next)
                assert word_rendered.state == 'output_check', word_rendered.error_code
                word_card = page.locator('article').filter(has=page.get_by_role('heading', name=f'可预览，待检查 · 版本 {word_version}', exact=True))
                expect(word_card).to_be_visible(timeout=20000)
                if word_card.get_by_role('button', name='查看输出', exact=True).count():
                    word_card.get_by_role('button', name='查看输出', exact=True).click()
                expect(word_card.locator('img[alt$="页预览"]')).to_have_count(8)
                assert word_card.locator('iframe').count() == 0
                assert word_card.get_by_role('link', name='下载 Word', exact=True).count() == 3
                settle_visuals()
                word_card.screenshot(path=str(output / 'word-only-output-previews.png'))
                checks.append('word-only-every-page-preview-without-pdf-download')
                # Exercise both other business loops through the same built UI,
                # using the uploaded synthetic source and real append-only records.
                page.goto(origin + app_url(f'/material/{material.pk}/question/new/'))
                page.locator('#id_original_number').fill('整合练习题')
                page.locator('#id_printed_text').fill('合成验收：3 + 5 = ?')
                page.locator('#id_reason').fill('对照本机合成原图录入')
                source_card = page.locator('.region-card').first
                open_disclosure('精确选择区域（键盘）', source_card)
                for field, value in [('x0','2'), ('y0','2'), ('x1','22'), ('y1','28')]:
                    source_card.locator('.coord-' + field).fill(value)
                source_card.locator('.add-coordinates').click()
                page.locator('#question-form > .form-actions button[value=draft]').click()
                expect(page.locator('.printed-text')).to_have_text('合成验收：3 + 5 = ?', use_inner_text=True)
                question_path = dict(parse_qsl(urlsplit(page.url).query))['screen']
                new_question_id = question_path.rstrip('/').split('/')[-1]
                new_question = db(lambda: EntityRecord.objects.get(kind='question', stable_id=new_question_id))
                page.locator('#id_action').select_option('accept')
                page.locator('#id_reason').fill('核对合成原图与题干')
                with page.expect_response(lambda r: r.request.method == 'POST'
                        and '/api/v1/workspace/submit/' in r.url
                        and f'/question/{new_question_id}/review/' in unquote(r.url)) as review_response:
                    page.get_by_role('button', name='记录审核决定', exact=True).click()
                review_result = review_response.value.json()
                assert review_response.value.status == 200, {
                    'status': review_response.value.status, 'error': review_result.get('error'),
                }
                assert review_result.get('redirect') == question_path, review_result.get('redirect')
                expect(page.locator('.workspace-page')).to_contain_text('已审核')
                assert db(lambda: EntityRecord.objects.get(pk=new_question.pk).published_revision_id) == new_question.head_revision_id
                page.goto(origin + app_url(f'/prints/?household={house.pk}'))
                page.get_by_role('tab', name='练习与整套五册', exact=True).click()
                expect(page.locator('#id_household')).to_have_value(str(house.pk))
                page.locator('#id_title').fill('整合验收无提示练习')
                page.locator('#id_purpose').select_option('independent_practice')
                page.locator(f'input[name=questions][value="{new_question.head_revision_id}"]').check()
                page.get_by_role('button', name='同时生成 PDF 与 Word', exact=True).click()
                expect(page.locator('.workspace-page h1')).to_have_text('整合验收无提示练习')
                snapshot_path = dict(parse_qsl(urlsplit(page.url).query))['screen']
                snapshot_id = int(snapshot_path.rstrip('/').split('/')[-1])
                from app.printing.models import ExportSnapshot
                practice = db(lambda: ExportSnapshot.objects.get(pk=snapshot_id))
                assert practice.provenance['answers'] == []
                with page.expect_response(lambda r: '/document.pdf/' in r.url and 'preview=1' in r.url) as practice_pdf:
                    page.get_by_role('link', name='预览 PDF', exact=True).click()
                assert practice_pdf.value.status == 200
                expect(page.get_by_role('dialog').locator('iframe')).to_be_visible()
                page.get_by_role('button', name='关闭预览', exact=True).click()
                with page.expect_download() as download:
                    page.get_by_role('link', name='下载 Word', exact=True).click()
                assert download.value.suggested_filename.endswith('.docx')
                settle_visuals()
                page.screenshot(path=str(output / 'practice-upload-question-export.png'), full_page=True)
                checks.append('uploaded-source-new-question-review-no-answer-pdf-and-word')

                page.goto(origin + app_url(f'/learning/profile/{f["learner"]}/attempt/new/'))
                for field, value in [('question_id',f['question']), ('attempt_kind','retest'),
                    ('source_kind','independent_answer'), ('independence','confirmed_independent'),
                    ('prompt_status','none_confirmed'), ('actual_date_state','known'), ('legibility','readable')]:
                    page.locator('#id_' + field).select_option(value)
                page.locator('#id_actual_date').fill('2026-10-05')
                page.locator('#id_answer_text').fill('8 厘米 · 本机合成复测')
                page.locator('#id_authorship_basis').fill('仅为合成验收：采用已明确确认的合成观察')
                page.locator('input[name=observation_values]').first.check()
                page.locator('#id_previous_attempt_id').select_option(f['attempt'])
                page.get_by_role('button', name='保存作答记录', exact=True).click()
                open_disclosure('回看这次作答的修改历史')
                expect(page.locator('.history-list')).to_contain_text('修订 1')
                retest_path = dict(parse_qsl(urlsplit(page.url).query))['screen']
                retest_id = urlsplit(retest_path).path.rstrip('/').split('/')[-1]
                retest = db(lambda: EntityRecord.objects.get(kind='attempt', stable_id=retest_id))
                assert retest.pk != attempt_entity.pk
                assert db(lambda: EntityRecord.objects.filter(household_id=house.pk, kind='attempt').count()) == attempt_count + 1
                page.goto(origin + app_url(f'/study/learner/{f["learner_entity"]}/schedule/new/'))
                page.locator('#id_question_revision_id').select_option(str(f['question_revision']))
                page.locator('#id_due_date').fill('2026-10-05')
                page.locator('#id_goal').fill('合成复测：检查乘法与单位')
                page.locator('#id_prompt_plan').fill('先独立完成，再核对')
                page.locator('#id_reason').fill('本机整合流程验收')
                page.get_by_role('button', name='保存计划', exact=True).click()
                expect(page.locator('.study-events')).to_be_visible()
                schedule_path = dict(parse_qsl(urlsplit(page.url).query))['screen']
                new_schedule_pk = int(schedule_path.rstrip('/').split('/')[-1])
                open_disclosure('修改计划与确认已有作答')
                page.locator('#id_action').select_option('completed')
                page.locator('#id_attempt_revision_id').select_option(str(retest.head_revision_id))
                page.locator('#id_reason').fill('绑定刚保存的合成复测，不推断掌握')
                page.get_by_role('button', name='追加计划事件', exact=True).click()
                expect(page.locator('.study-events').last).to_contain_text('已完成复习')
                from app.study.models import ScheduleRevision
                events = db(lambda: list(ScheduleRevision.objects.filter(schedule_id=new_schedule_pk).order_by('revision_no')))
                assert [event.action for event in events] == ['planned', 'completed']
                assert events[-1].completed_attempt_revision_id == retest.head_revision_id
                page.goto(origin + app_url(f'/study/learner/{f["learner_entity"]}/report/'))
                expect(page.locator('.report-attempts')).to_contain_text('8 厘米 · 本机合成复测')
                settle_visuals()
                page.screenshot(path=str(output / 'retest-plan-report.png'), full_page=True)
                checks.append('new-retest-plan-bind-real-attempt-and-report-preserve-history')
                # An unfinished plan remains private browser input. Exercise
                # both retained views and App's real module/learner guards.
                page.goto(origin + app_url(view='progress') + '&learner=' + f['learner'])
                page.get_by_role('button', name='新增复测计划', exact=True).click()
                plan_goal = page.get_by_role('textbox', name='复测目标（必填）', exact=True)
                expect(plan_goal).to_be_visible()
                plan_goal.fill('浏览器未保存计划：取消离开后继续编辑')
                page.get_by_role('tab', name='学习证据', exact=True).click()
                page.get_by_role('tab', name='复测计划', exact=True).click()
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.get_by_role('button', name=re.compile('^已完成')).click()
                page.get_by_role('button', name=re.compile('^逾期')).click()
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('navigation', name='主导航').get_by_role('button', name='资料整理', exact=True).click()
                assert dict(parse_qsl(urlsplit(page.url).query))['view'] == 'progress'
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('combobox', name='学习者', exact=True).select_option(second_learner)
                expect(page.get_by_role('combobox', name='学习者', exact=True)).to_have_value(f['learner'])
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button', name='刷新全部', exact=True).click()
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.once('dialog', lambda dialog: dialog.dismiss())
                page.get_by_role('button', name='收起新计划', exact=True).click()
                expect(plan_goal).to_have_value('浏览器未保存计划：取消离开后继续编辑')
                page.once('dialog', lambda dialog: dialog.accept())
                page.get_by_role('button', name='收起新计划', exact=True).click()
                expect(plan_goal).not_to_be_visible()
                checks.append('unfinished-plan-tabs-filters-module-learner-and-discard-protection')
                # Capture the seven normal entry pages at both widths, with
                # secondary areas left closed as an actual user first sees them.
                for width in (1280, 1920, 2560, 390):
                    page.set_viewport_size({'width': width, 'height': {1280: 800, 1920: 1080, 2560: 1440, 390: 844}[width]})
                    for view in ('overview', 'materials', 'knowledge', 'learning', 'progress', 'documents', 'settings'):
                        page.goto(origin + app_url(view=view) + '&learner=' + f['learner'])
                        if view == 'overview':
                            expect(page.get_by_role('heading', name='今天从哪里开始？')).to_be_visible()
                            expect(page.get_by_role('heading', name='当前范围摘要', exact=True)).to_be_visible()
                            expect(page.get_by_text('正在整理学习证据…', exact=True)).not_to_be_visible()
                            # Plans load independently from the evidence summary.
                            next_tasks = page.get_by_role('region', name='接下来做什么', exact=True)
                            expect(next_tasks.get_by_text('正在读取计划…', exact=True)).not_to_be_visible()
                            expect(next_tasks.get_by_role('link').first).to_be_visible()
                        elif view == 'materials':
                            expect(page.get_by_role('button', name=re.compile('合成容器验收 PC 资料'))).to_be_visible()
                            expect(page.get_by_text('正在读取资料列表…', exact=True)).not_to_be_visible()
                            expect(page.get_by_role('tab', name=re.compile('^原图与进度'))).to_have_attribute('aria-selected', 'true')
                        elif view == 'progress':
                            expect(page.get_by_role('heading', name='复测计划', exact=True)).to_be_visible()
                            expect(page.get_by_role('tab', name='复测计划', exact=True)).to_have_attribute('aria-selected', 'true')
                            expect(page.get_by_role('button', name=re.compile('^今天'))).to_have_attribute('aria-pressed', 'true')
                            page.get_by_role('button', name=re.compile('^逾期')).click()
                            expect(page.get_by_text('合成复测：检查乘法与单位', exact=True)).not_to_be_visible()
                            page.get_by_role('button', name=re.compile('^已完成')).click()
                            expect(page.get_by_text('合成复测：检查乘法与单位', exact=True)).to_be_visible()
                            page.get_by_role('button', name=re.compile('^近期')).click()
                        elif view == 'documents':
                            expect(page.get_by_role('tab', name='最近成果', exact=True)).to_have_attribute('aria-selected', 'true')
                            recent = page.get_by_role('region', name='最近成果', exact=True)
                            expect(recent).to_be_visible()
                            recent_rows = recent.get_by_role('listitem').filter(
                                has=page.get_by_role('heading', name=material.title, exact=True))
                            expect(recent_rows.first).to_be_visible()
                            assert recent_rows.count() >= 1, 'recent catalogue should allow one or more outputs for the fixture material'
                        else:
                            expect(page.locator('.workspace-page h1')).to_be_visible()
                            if view == 'settings':
                                expect(page.get_by_role('heading', name='现有成员', exact=True)).to_be_visible()
                                expect(page.locator('#id_create_username')).not_to_be_visible()
                        settle_visuals()
                        assert page.get_by_role('combobox', name='家庭', exact=True).count() == 1, (view, width, 'duplicated household selector')
                        assert page.get_by_role('combobox', name='学习者', exact=True).count() <= 1, (view, width, 'duplicated learner selector')
                        check_business_text(page.locator('#content'), f'entry-{view}-{width}')
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), (view, width)
                        page.screenshot(path=str(output / f'entry-{view}-{width}.png'), full_page=True)
                        if width == 1920:
                            if view == 'overview':
                                open_disclosure('家长整理与记录')
                                settle_visuals()
                            check_text_contrast(view, 'light')
                            page.evaluate("document.documentElement.classList.add('dark')")
                            settle_visuals()
                            check_text_contrast(view, 'dark')
                            page.screenshot(path=str(output / f'entry-{view}-1920-dark.png'), full_page=True)
                            page.evaluate("document.documentElement.classList.remove('dark')")
                            if view == 'overview':
                                page.locator('summary').filter(has_text=re.compile('^家长整理与记录$')).click()
                        if width >= 1280:
                            measured = page.locator('#content').evaluate('''main => {
                                const rect = main.getBoundingClientRect();
                                const actions = [...main.querySelectorAll('button, a, input:not([type=hidden]), select')]
                                    .filter(el => el.getClientRects().length && getComputedStyle(el).visibility !== 'hidden');
                                const first = actions[0]?.getBoundingClientRect();
                                const workspace = [...main.children].reverse().find(el => el.getClientRects().length && !['H1', 'NAV'].includes(el.tagName));
                                return {main_width: rect.width, available_width: innerWidth - rect.x,
                                    workspace_width: workspace?.getBoundingClientRect().width,
                                    first_action_top: first?.top, first_action: actions[0]?.textContent.trim() || actions[0]?.name};
                            }''')
                            limit = 1056 if view == 'settings' else 1440  # DESIGN.md: 66rem settings / 90rem workspace
                            assert measured['main_width'] <= min(measured['available_width'], limit) + 2, (view, width, measured)
                            assert measured['workspace_width'] <= measured['main_width'] + 2, (view, width, measured)
                            assert measured['main_width'] >= min(measured['available_width'], limit) * .85, (view, width, measured)
                            assert measured['first_action_top'] is not None and measured['first_action_top'] <= 220, (view, width, measured)
                            assert page.get_by_role('navigation', name='主导航').get_by_role('button').count() == 7
                            ux_measurements.append({'view':view, 'width':width, **measured})
                        if width >= 1920 and view in ('materials', 'progress'):
                            if view == 'progress':
                                # Relative-date buckets may legitimately be empty
                                # as the fixture crosses from upcoming to today.
                                # Use the known completed fixture for row density.
                                page.get_by_role('button', name=re.compile('^已完成')).click()
                                expect(page.get_by_text('合成复测：检查乘法与单位', exact=True)).to_be_visible()
                            rows = (page.get_by_role('region', name='资料列表', exact=True).locator('button[aria-pressed]')
                                if view == 'materials' else page.locator('#progress-workspace-plans-panel tbody tr'))
                            heights = rows.evaluate_all('''rows => rows.filter(row => row.getClientRects().length && !row.querySelector('td[colspan]'))
                                .map(row => row.getBoundingClientRect().height)''')
                            # Summary rows carry multiple real fields; expanded history
                            # remains outside this gate. Keep readable bounded density.
                            upper = 96 if view == 'materials' else 200
                            assert heights and all(44 <= height <= upper for height in heights), (view, width, heights)
                            row_measurements.append({'view':view, 'width':width, 'heights':heights})
                        if view == 'documents':
                            parent_tab = page.get_by_role('tab', name='家长解析', exact=True)
                            parent_tab.click()
                            expect(parent_tab).to_have_attribute('aria-selected', 'true')
                            solutions = page.get_by_role('tabpanel', name='家长解析', exact=True)
                            expect(solutions).to_be_visible()
                            source_rows = solutions.get_by_role('listitem').filter(
                                has=page.get_by_role('heading', name=material.title, exact=True))
                            expect(source_rows.first).to_be_visible()
                            assert source_rows.count() >= 1, 'solution launcher should include the fixture material'
                            source_rows.first.get_by_role('button', name='查看文档与历史', exact=True).click()
                            expect(page.get_by_role('tab', name=re.compile('^生成文件'))).to_have_attribute('aria-selected', 'true')
                            expect(page.locator('#solution-editor-panel')).not_to_be_visible()
                            expect(page.locator('#solution-outputs-panel article').first).to_be_visible()
                            settle_visuals()
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), ('solution-outputs', width)
                            page.screenshot(path=str(output / f'solution-viewing-{width}.png'), full_page=True)
                            page.goto(origin + app_url(view='documents'))
                            parent_tab = page.get_by_role('tab', name='家长解析', exact=True)
                            expect(page.get_by_role('tab', name='最近成果', exact=True)).to_have_attribute('aria-selected', 'true')
                            expect(page.get_by_role('button', name='制作整套五册', exact=True)).not_to_be_visible()
                            parent_tab.click()
                            expect(parent_tab).to_have_attribute('aria-selected', 'true')
                            solutions = page.get_by_role('tabpanel', name='家长解析', exact=True)
                            source_rows = solutions.get_by_role('listitem').filter(
                                has=page.get_by_role('heading', name=material.title, exact=True))
                            expect(source_rows.first).to_be_visible()
                            assert source_rows.count() >= 1, 'solution launcher should include the fixture material before the five-book action'
                            source_rows.first.get_by_role('button', name='制作整套五册', exact=True).click()
                            expect(page.locator('.workspace-page h1')).to_contain_text('五册')
                            assert dict(parse_qsl(urlsplit(page.url).query))['screen'].startswith(f'/prints/materials/{material.pk}/five-books/')
                    if width == 390:
                        page.goto(origin + app_url('/__app__/solutions/' + str(material.pk) + '/', view='documents'))
                        page.get_by_role('tab', name='编辑讲解', exact=True).click()
                        expect(page.get_by_label('题目标题', exact=True)).to_be_visible()
                        settle_visuals()
                        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2')
                        page.screenshot(path=str(output / 'solution-editor-390.png'), full_page=True)
                page.set_viewport_size({'width': 1440, 'height': 1000})
                checks.append('seven-entry-pages-and-document-viewing-1280-1920-2560-and-390')
                checks.append('seven-entry-light-and-dark-text-contrast')
                checks.append('ordinary-material-and-plan-row-density')
                page.goto(origin + app_url('/knowledge/?household_id=' + house.pk))
                knowledge_tab = page.get_by_role('tab', name='知识点', exact=True)
                knowledge_tab.click()
                knowledge_tab.press('ArrowRight')
                expect(page.get_by_role('tab', name='方法', exact=True)).to_be_focused()
                expect(knowledge_tab).to_have_attribute('aria-selected', 'true')
                page.get_by_role('tab', name='方法', exact=True).press('Enter')
                assert dict(parse_qsl(urlsplit(page.url).query))['tab'] == 'methods'
                page.reload()
                expect(page.get_by_role('tab', name='方法', exact=True)).to_have_attribute('aria-selected', 'true')
                page.get_by_role('tab', name='题目', exact=True).click()
                page.locator('#id_number').fill('待筛选题号')
                page.get_by_role('tab', name='知识点', exact=True).click()
                page.get_by_role('tab', name='题目', exact=True).click()
                expect(page.locator('#id_number')).to_have_value('待筛选题号')
                page.locator('#id_number').fill('')
                checks.append('native-tabs-keyboard-url-refresh-and-filter-input-preserved')
                page.goto(origin + app_url(view='settings'))
                page.locator('#members-panel-create > summary').click()
                page.locator('#id_create_username').fill(actor.username)
                page.locator('#id_create_password1').fill('synthetic-validation-only-123!')
                page.locator('#id_create_password2').fill('synthetic-validation-only-123!')
                user_count = db(lambda: get_user_model().objects.count())
                with page.expect_response(lambda r: r.request.method == 'POST' and '/api/v1/workspace/submit/' in r.url) as account_error:
                    page.get_by_role('button', name='添加成员并创建登录账号', exact=True).click()
                assert account_error.value.status == 400
                expect(page.locator('.workspace-page .errorlist').first).to_be_visible()
                expect(page.locator('#id_create_username')).to_be_visible()
                assert db(lambda: get_user_model().objects.count()) == user_count
                checks.append('settings-account-error-opens-required-form-without-new-account')
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
                login(actor)
                from verify_ux_remediation import verify as verify_ux_remediation
                verify_ux_remediation(page, origin, app_url, db, actor, house, material, f, output, checks)
                from verify_acceptance_follow_up import verify as verify_acceptance_follow_up
                verify_acceptance_follow_up(page, origin, app_url, db, actor, house, material, f, output, checks)
                from verify_design_system import verify as verify_design_system
                verify_design_system(page, origin, app_url, output, checks)
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
        report = {'browser_mode': 'headed Chromium on private virtual display' if os.environ.get('SWB_PC_HEADED') == '1' else 'headless full Chromium', 'checks':checks, 'matrix':matrix, 'template_coverage':sorted(expected_templates),
                  'errors':errors, 'external':external, 'leaks':leaks, 'ux_measurements':ux_measurements,
                  'theme_contrast':theme_contrast, 'row_measurements':row_measurements}
        (output / 'verification.local.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        for path in output.rglob('*'): path.chmod(0o700 if path.is_dir() else 0o600)
    print(json.dumps({'checks':len(checks), 'pages':len(matrix), 'report':str(output / 'verification.local.json')}, ensure_ascii=False))


if __name__ == '__main__': main()
