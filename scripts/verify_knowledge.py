#!/usr/bin/env python3
"""Four anonymous knowledge companions, private files, and an actual empty restore.

Only the owned synthetic runner may invoke this script. Original source pixels
are retained, model calls are prohibited, and Word client acceptance is unknown.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4
from zipfile import ZipFile

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from verify_business import require_owned_database


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


def tree_receipt(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise RuntimeError('Synthetic restore cannot follow a symlink')
        if path.is_file():
            result[str(path.relative_to(root))] = {'sha256': sha256(path.read_bytes()).hexdigest(),
                'bytes': path.stat().st_size, 'mode': oct(path.stat().st_mode & 0o777)}
    return result


def database_receipt(dbname):
    with psycopg.connect(host=os.environ['SWB_DB_HOST'], dbname=dbname, user='postgres') as conn:
        tables = [row[0] for row in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        result = {}
        for table in tables:
            rows = conn.execute(sql.SQL('SELECT to_jsonb(t)::text FROM {} t ORDER BY to_jsonb(t)::text').format(sql.Identifier(table))).fetchall()
            encoded = json.dumps([json.loads(row[0]) for row in rows], ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
            result[table] = {'rows': len(rows), 'sha256': sha256(encoded).hexdigest()}
        sequences = dict(conn.execute("SELECT sequencename,last_value FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename"))
    return {'tables': result, 'sequences': sequences}


def empty_restore(owner, output):
    """Stop writers first; pair the exact database and file snapshot, then restore."""
    data_root = Path(os.environ['SWB_DATA_ROOT'])
    backup = output / 'paired-backup'; backup.mkdir(mode=0o700)
    original = database_receipt('swb_synthetic')
    files = tree_receipt(data_root)
    details = json.loads(subprocess.check_output(['docker', 'inspect', 'swb-synthetic-' + owner], text=True))[0]
    assert details['Config']['Labels'].get('study-workbench.test-owner') == owner
    assert details['HostConfig']['NetworkMode'] == 'none' and not details['HostConfig']['PortBindings']
    cid = details['Id']
    dump = backup / 'database.dump'
    with dump.open('wb') as stream:
        subprocess.run(['docker', 'exec', cid, 'pg_dump', '-U', 'postgres', '-Fc', 'swb_synthetic'], stdout=stream, check=True)
    dump.chmod(0o600)
    shutil.copytree(data_root, backup / 'files', copy_function=shutil.copy2)
    assert tree_receipt(backup / 'files') == files
    write_json(backup / 'receipt.local.json', {'database': original, 'files': files,
        'dump_sha256': sha256(dump.read_bytes()).hexdigest()})
    restored_name = 'swb_knowledge_restored'
    with psycopg.connect(host=os.environ['SWB_DB_HOST'], dbname='postgres', user='postgres', autocommit=True) as conn:
        assert not conn.execute('SELECT 1 FROM pg_database WHERE datname=%s', (restored_name,)).fetchone()
        conn.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(restored_name)))
    assert database_receipt(restored_name) == {'tables': {}, 'sequences': {}}
    with dump.open('rb') as stream:
        subprocess.run(['docker', 'exec', '-i', cid, 'pg_restore', '-U', 'postgres', '--exit-on-error',
            '--dbname', restored_name, '--no-owner', '--no-acl'], stdin=stream, check=True)
    restored_root = data_root.parent / 'knowledge-restored-files'
    assert not restored_root.exists()
    shutil.copytree(backup / 'files', restored_root, copy_function=shutil.copy2)
    assert database_receipt(restored_name) == original
    assert tree_receipt(restored_root) == files
    return restored_name, restored_root, {'database_tables': len(original['tables']),
        'database_rows': sum(item['rows'] for item in original['tables'].values()),
        'files': len(files), 'sequences': len(original['sequences']), 'all_rows_sequences_and_files_identical': True}


def start_server(output, env=None):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    log = (output / ('restored-server.log' if env else 'server.log')).open('w')
    process = subprocess.Popen([sys.executable, 'manage.py', 'runserver', f'127.0.0.1:{port}',
        '--noreload', '--insecure'], cwd=ROOT, stdout=log, stderr=log, env=env)
    log.close()
    deadline = time.monotonic() + 20
    while True:
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.3): break
        except OSError:
            if process.poll() is not None or time.monotonic() > deadline:
                process.terminate(); process.wait(timeout=10)
                raise RuntimeError('Owned knowledge server did not start')
            time.sleep(.1)
    return process, f'http://127.0.0.1:{port}'


def stop_server(process):
    process.terminate()
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--owner', required=True)
    args = parser.parse_args()
    require_owned_database(args.owner)
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.db import connections
    from app.persistence import services as core
    from app.persistence.models import EntityRecord
    from app.web import services as materials, subjects
    from app.solutions import jobs, queries, rendering, services
    from app.solutions.models import SolutionOutput, SolutionRevision
    from app.ai.models import ModelRun
    from app.exports.snapshots import verify_snapshot
    from lxml import etree
    from PIL import Image, ImageDraw, ImageFont
    from playwright.sync_api import sync_playwright, expect
    from tests.solutions.knowledge_fixtures import SAMPLES

    output = ROOT / 'artifacts/knowledge-verification' / args.owner
    output.mkdir(parents=True, mode=0o700)
    for parent in (output, output.parent, output.parent.parent): parent.chmod(0o700)
    snapshots = ROOT / 'exports' / ('knowledge-trial-' + args.owner)
    snapshots.mkdir(parents=True, mode=0o700)
    snapshots.parent.chmod(0o700)
    password = secrets.token_urlsafe(24)
    actor = get_user_model().objects.create_user(username='knowledge-' + uuid4().hex[:10], password=password)
    house = core.create_household(actor, '匿名知识讲解试用')
    other_house = core.create_household(actor, '匿名导航范围核对')
    fixtures = {}
    font = ImageFont.truetype('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', 22)
    for profile, sample in SAMPLES.items():
        material = materials.create_material(actor, house.pk, '匿名试用 · ' + sample['title'], uuid4().hex)
        source = Image.new('RGBA', (1000, 700), 'white'); draw = ImageDraw.Draw(source)
        lines = [sample['title'], '自行编写的匿名资料。科学与人文记录为虚构示例。', *textwrap.wrap(sample['definitions'], 36),
            *textwrap.wrap(sample['statement'], 36)]
        for index, line in enumerate(lines): draw.text((45, 35 + index * 40), line, font=font, fill='black')
        stream = BytesIO(); source.save(stream, format='PNG')
        uploaded = materials.upload_page(actor, material.pk, SimpleUploadedFile(profile + '.png', stream.getvalue(), content_type='image/png'), uuid4().hex)
        fixtures[profile] = {'material': material, 'page_id': uploaded['page_id'], 'source_sha256': sha256(stream.getvalue()).hexdigest()}
    baseline_entities, baseline_runs = EntityRecord.objects.count(), ModelRun.objects.count()
    checks, errors, external, measurements, documents = [], [], [], [], []
    pool = ThreadPoolExecutor(max_workers=1)
    def db(fn):
        def call():
            try: return fn()
            finally: connections.close_all()
        return pool.submit(call).result(timeout=180)
    def app_url(view='knowledge', screen='', **extra):
        return '/app/?' + urlencode({'view': view, 'household': str(house.pk), **({'screen': screen} if screen else {}), **extra})
    server, origin = start_server(output)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width':1440, 'height':1000}, accept_downloads=True)
            def restrict(route):
                if route.request.url.startswith(origin + '/'): route.continue_()
                else: external.append(route.request.url); route.abort()
            context.route('**/*', restrict)
            page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
            def login():
                page.goto(origin + '/accounts/login/')
                page.locator('#id_username').fill(actor.username); page.locator('#id_password').fill(password)
                page.get_by_role('button', name='登录', exact=True).click()
                page.wait_for_url(lambda url: '/accounts/login/' not in str(url))
            def disclosure(label):
                summary = page.locator('summary').filter(has_text=re.compile('^' + re.escape(label)))
                expect(summary).to_have_count(1)
                if not summary.evaluate('(el) => el.parentElement.open'): summary.click()
            def capture(name):
                page.evaluate('document.fonts.ready')
                page.evaluate('window.scrollTo({top:0,left:0,behavior:"instant"})')
                page.wait_for_function('window.scrollY === 0')
                page.screenshot(path=str(output / (name + '.png')), full_page=True)
                dimensions = page.evaluate('({width: innerWidth, scroll: document.documentElement.scrollWidth})')
                assert dimensions['scroll'] <= dimensions['width'] + 2, (name, dimensions)
                measurements.append({'view': name, **dimensions})
            def list_add(title, values):
                scope = page.get_by_role('heading', name=title, exact=True).locator('../..')
                for index, value in enumerate(values, 1):
                    scope.get_by_role('button', name='添加', exact=True).click()
                    page.get_by_role('textbox', name=f'{title} {index}', exact=True).fill(value)
            login()
            for sample_index, (profile, fixture) in enumerate(fixtures.items()):
                sample = SAMPLES[profile]; mid = str(fixture['material'].pk)
                # The initial unknown classification is visible and explicitly revised.
                page.goto(origin + app_url('materials', material=mid))
                expect(page.get_by_role('heading', name=fixture['material'].title, exact=True)).to_be_visible()
                page.get_by_role('combobox', name='资料学科', exact=True).select_option('unknown')
                rows = page.get_by_role('region', name='资料列表', exact=True).locator('button[aria-pressed]')
                expect(rows).to_have_count(4 - sample_index)
                disclosure('资料学科')
                page.get_by_role('combobox', name='学校学科', exact=True).select_option(sample['subject'])
                page.get_by_role('textbox', name='分类依据').fill('匿名原页与课程人工核对；不推断讲解依据类别。')
                page.get_by_role('button', name='保存分类新版本', exact=True).click()
                expect(page.get_by_text('学科分类已保存为第 1 版。', exact=True)).to_be_visible()
                expect(rows).to_have_count(3 - sample_index)
                page.goto(origin + app_url(screen=f'/__app__/knowledge-explanations/{mid}/', household=str(other_house.pk)))
                expect(page.get_by_role('heading', name=fixture['material'].title + ' · 知识点讲解', exact=True)).to_be_visible()
                assert parse_qs(urlsplit(page.url).query)['household'] == [str(house.pk)]
                disclosure('讲解文档设置')
                page.get_by_role('textbox', name='文档标题', exact=True).fill('匿名完整讲解 · ' + sample['title'])
                page.get_by_role('textbox', name='学习层级', exact=True).fill('初中匿名软件试用')
                page.get_by_role('textbox', name='讲次名称', exact=True).fill(sample['title'])
                page.get_by_role('combobox', name='讲解依据类别', exact=True).select_option(profile)
                for legend in ('知识清单', '逐知识点', '按讲次', '完整合集'):
                    group = page.locator('fieldset').filter(has=page.locator('legend', has_text=legend))
                    group.get_by_role('checkbox', name='PDF', exact=True).check()
                    group.get_by_role('checkbox', name='Word', exact=True).check()
                page.get_by_role('button', name='添加知识点', exact=True).click()
                page.get_by_role('textbox', name='知识名称', exact=True).fill(sample['title'])
                page.get_by_role('combobox', name='知识性质', exact=True).select_option(sample['kind'])
                for label, value in [('原页结论', sample['statement']), ('完整结论', sample['statement']), ('定义、字母与变量', sample['definitions'])]:
                    page.get_by_role('textbox', name=label, exact=True).fill(value)
                list_add('适用条件', sample['conditions'])
                page.get_by_role('button', name='记录整页来源（区域未知）', exact=True).click()
                page.get_by_role('textbox', name='印刷页码（未知可留空）', exact=True).fill('1')
                page.get_by_role('tab', name='证明与讲解', exact=True).click()
                for label, value in zip(('先想什么', '方法／构造及目的', '完整推导／依据', '结论', '易错点／适用限制'), sample['explanation'], strict=True):
                    page.get_by_role('textbox', name=label, exact=True).fill(value)
                if profile == 'mathematics':
                    disclosure('第 3 步公式、图示与分页')
                    page.get_by_role('textbox', name='第 3 步公式表达式', exact=True).fill('2*(m+n)')
                    preview = page.get_by_role('region', name='第 3 步公式预览', exact=True)
                    expect(preview).to_have_text(re.compile(r'2.*m.*n'))
                    expect(preview.get_by_role('status')).to_have_count(0)
                    expect(preview.get_by_role('alert')).to_have_count(0)
                page.get_by_role('tab', name='订正与图示', exact=True).click()
                list_add('待核项与依据缺口', ['自行编写的匿名材料；科学与人文为虚构记录，不代表真实实验或历史。'])
                page.get_by_role('textbox', name='本次保存依据', exact=True).fill('人工逐项核对原页、完整结论、条件和五部分讲解。')
                page.get_by_role('button', name='保存为新版本', exact=True).click()
                expect(page.get_by_text('已保存为版本 1。', exact=True)).to_be_visible()
                page.get_by_role('button', name='明确确认讲解', exact=True).click()
                expect(page.get_by_text('当前正式版本已明确确认。', exact=False)).to_be_visible()
                page.get_by_role('button', name='生成 PDF / Word', exact=True).click()
                expect(page.get_by_text('等待生成', exact=False).first).to_be_visible()
                row = db(jobs.execute_next)
                result_id = row.pk
                assert row.state == 'output_check', (profile, row.error_code)
                page.get_by_role('tab', name=re.compile('生成文件')).click()
                expect(page.get_by_text('可预览，待检查', exact=False).first).to_be_visible(timeout=12000)
                details = db(lambda: queries.output_row(SolutionOutput.objects.get(pk=result_id)))
                assert set(details['checks']) == {'content', 'subject', 'pdf_visual', 'word_pc', 'word_macos'}
                assert all(check['status'] == 'not_tested' for check in details['checks'].values())
                assert len(details['documents']) == 4 and all(not document['question_ids'] for document in details['documents'])
                dest = output / 'documents' / profile; dest.mkdir(parents=True, mode=0o700)
                for document in details['documents']:
                    for format_name in ('pdf', 'docx'):
                        path = db(lambda d=document, fmt=format_name: rendering.output_file(row, d['id'], 'document.' + fmt))
                        target = dest / (document['organization'] + '.' + format_name)
                        shutil.copy2(path, target); target.chmod(0o600)
                        if format_name == 'docx':
                            verified = snapshots / profile / path.parent.name
                            shutil.copytree(path.parent, verified)
                            verify_snapshot(verified)
                            with ZipFile(target) as archive:
                                xml = etree.fromstring(archive.read('word/document.xml'))
                                plain = ''.join(xml.xpath('//w:t/text()', namespaces={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}))
                                assert sample['statement'] in plain and '未分类' not in plain
                        else:
                            text = subprocess.check_output(['pdftotext', str(target), '-'], text=True)
                            assert sample['title'] in text
                            if document['organization'] != 'inventory':
                                assert all(label in text for label in ('先想什么', '构造', '推导', '结论', '易错点'))
                            preview_prefix = dest / (document['organization'] + '-page')
                            subprocess.run(['pdftoppm', '-scale-to', '1200', '-png', str(target), str(preview_prefix)], check=True)
                    documents.append({'profile': profile, 'organization': document['organization'], 'page_count': document['page_count'],
                        'directory':str(verified),
                        'files': {fmt: sha256((dest / (document['organization'] + '.' + fmt)).read_bytes()).hexdigest() for fmt in ('pdf', 'docx')}})
                with page.expect_download(predicate=lambda item: urlsplit(item.url).path == urlsplit(details['zip_url']).path) as download:
                    page.get_by_role('link', name='下载全部 ZIP', exact=True).click()
                download.value.save_as(str(dest / 'complete.zip'))
                with ZipFile(dest / 'complete.zip') as archive:
                    assert not any(name.startswith('sources/') for name in archive.namelist())
                    assert len([name for name in archive.namelist() if name.endswith(('.pdf', '.docx'))]) == 8
                # Historical mode stays read-only; continued edits append a new version.
                page.get_by_role('tab', name=re.compile('历史版本')).click()
                page.get_by_role('button', name='打开并对照', exact=True).first.click()
                expect(page.get_by_text('历史版本对照', exact=True)).to_be_visible()
                expect(page.locator('p:visible').filter(has_text=re.compile(re.escape(sample['statement']))).first).to_be_visible()
                capture(profile + '-history')
                for width in (1280, 1920, 2560, 390):
                    page.set_viewport_size({'width':width, 'height':1000 if width > 390 else 844})
                    page.get_by_role('tab', name='编辑讲解', exact=True).click()
                    page.get_by_role('tab', name='结论与来源', exact=True).click()
                    capture(profile + '-source-' + str(width))
                page.set_viewport_size({'width':1440, 'height':1000})
                assert db(lambda: subjects.current(fixture['material']))['subject'] == sample['subject']
                checks.append(profile + ': UI classification, full proof, save, confirm, generation, history, ZIP, PDF/Word structure and four widths')
            # All three document modes remain separate in the same app.
            page.goto(origin + app_url('documents'))
            for label in ('知识点讲解', '逐题讲解', '五册与练习'):
                page.get_by_role('tab', name=label, exact=True).click(); capture('document-mode-' + label)
            assert not errors and not external, (errors, external)
            browser.close()
    finally:
        stop_server(server); pool.shutdown(wait=True); connections.close_all()
    assert EntityRecord.objects.count() == baseline_entities
    assert ModelRun.objects.count() == baseline_runs
    assert SolutionRevision.objects.filter(mode='knowledge').count() == 4
    assert SolutionRevision.objects.filter(mode='solution', material__household=house).count() == 0
    from app.web.models import MaterialPage
    for fixture in fixtures.values():
        source_page = MaterialPage.objects.get(pk=fixture['page_id'])
        original = materials.asset_path(source_page.image.payload['storage_key'], source_page.image.sha256)
        assert sha256(original.read_bytes()).hexdigest() == fixture['source_sha256']
    restored_name, restored_root, recovery = empty_restore(args.owner, output)
    env = dict(os.environ, SWB_DB_NAME=restored_name, SWB_DATA_ROOT=str(restored_root))
    server, restored_origin = start_server(output, env)
    try:
        # Use a real new server and new session against the restored database.
        import urllib.request
        from http.cookiejar import CookieJar
        client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        html = client.open(restored_origin + '/accounts/login/').read().decode()
        csrf = re.search('name="csrfmiddlewaretoken" value="([^"]+)"', html).group(1)
        response = client.open(restored_origin + '/accounts/login/', urlencode({'username':actor.username, 'password':password,
            'csrfmiddlewaretoken':csrf}).encode())
        assert '/accounts/login/' not in response.url
        for fixture in fixtures.values():
            restored = json.loads(client.open(restored_origin + f'/api/v1/materials/{fixture["material"].pk}/knowledge-explanations/').read())
            assert restored['revision']['version'] == 1 and restored['revision']['confirmed']
            assert len(restored['outputs']) == 1 and len(restored['outputs'][0]['documents']) == 4
            for document in restored['outputs'][0]['documents']:
                assert client.open(restored_origin + document['pdf_url']).read().startswith(b'%PDF-')
            assert client.open(restored_origin + restored['pages'][0]['preview_url']).read()
        recovery['restored_account_history_sources_and_16_pdfs_readable'] = True
    finally: stop_server(server)
    write_json(output / 'report.local.json', {'status':'PASS', 'scope':'owned anonymous local HTTP; no formal deployment',
        'checks':checks, 'documents':documents, 'measurements':measurements, 'page_errors':errors,
        'external_requests':external, 'word_pc':'not_tested', 'word_macos':'not_tested',
        'no_new_question_learning_or_model_records':True, 'original_source_bytes_unchanged':True, 'recovery':recovery})
    write_json(output / 'office-source.local.json', {'documents':[{'directory':item['directory']} for item in documents]})
    for path in output.rglob('*'):
        path.chmod(0o700 if path.is_dir() else 0o600)
    for path in snapshots.rglob('*'):
        path.chmod(0o700 if path.is_dir() else 0o600)
    print(json.dumps({'status':'PASS', 'checks':len(checks), 'documents':len(documents), 'recovery':recovery,
        'report':str(output / 'report.local.json')}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
