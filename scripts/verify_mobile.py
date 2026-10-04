#!/usr/bin/env python3
"""Build MOB-01 in a new owned Compose project; never touch 36 or global CA trust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPSHandler, HTTPCookieProcessor, build_opener
import uuid

import verify_container as base


ROOT = base.ROOT
MOBILE_COMPOSE = ROOT / 'compose.mobile.yaml'
CADDY_IMAGE = 'caddy@sha256:df7f1c2fb114453b951de51a98efc010db1655a92c2e86be6706714e2417a78d'


def compose(project, env, *args, input_text=None):
    return base.command(['docker', 'compose', '-f', str(base.COMPOSE_FILE), '-f', str(MOBILE_COMPOSE),
        '-p', project, *args], env=env, input_text=input_text)


class TLSBrowser(base.Browser):
    def __init__(self, origin, ca_file):
        super().__init__(origin)
        self.opener = build_opener(HTTPSHandler(context=ssl.create_default_context(cafile=str(ca_file))), HTTPCookieProcessor())

    def request(self, path, *, data=None, headers=None):
        headers = dict(headers or {})
        if data is not None:
            headers['Origin'] = self.base_url
        return super().request(path, data=data, headers=headers)


def exec_python(project, env, code, payload=None):
    result = compose(project, env, 'exec', '-T', 'web', 'python', '-c', code,
        input_text=json.dumps(payload, ensure_ascii=False) if payload is not None else None)
    return json.loads(result.stdout)


def wait_tls(browser, timeout=45):
    deadline = time.monotonic() + timeout
    while True:
        try:
            assert browser.request('/healthz')[0] == 200
            return
        except OSError:
            if time.monotonic() >= deadline: raise
            time.sleep(1)


LINK_CODE = r'''import django,json,sys,uuid
django.setup()
from django.contrib.auth import get_user_model
from app.persistence.models import EntityRecord
from app.persistence.services import review_context,review_revision
from app.web import knowledge_services
from app.web.models import MaterialPage,QuestionSource
p=json.load(sys.stdin);actor=get_user_model().objects.get(username=p['username'])
page=MaterialPage.objects.select_related('material','image').get(pk=p['page_id'])
source=QuestionSource.objects.get(material=page.material,original_number='合成验收题')
question=EntityRecord.objects.get(kind='question',head_revision=source.revision)
node=EntityRecord.objects.get(household=question.household,kind='knowledge',stable_id='knowledge-fractions')
link=knowledge_services.create_link(actor,question.household_id,kind='knowledge',
    node_revision_id=str(node.published_revision_id),question_revision_id=str(question.head_revision_id),
    role='applies',request_key=str(uuid.uuid4()),reason='合成 HTTPS 双向追溯')
context=review_context(actor,question.household_id,link['revision_id'])
review_revision(actor,question.household_id,link['revision_id'],action='accept',
    expected_head=context['expected_head'],expected_dependencies=context['expected_dependencies'],
    expected_decision_id=context['expected_decision_id'],request_key=str(uuid.uuid4()),reason='合成关系审核')
attempts=list(EntityRecord.objects.filter(household=question.household,kind='attempt',
    head_revision__payload__question_revision_id=str(question.head_revision_id)))
assert len(attempts)==3
learner=attempts[0].identity['learner_id']
print(json.dumps({'node':f'/knowledge/entity/{node.pk}/',
    'knowledge_question':f'/knowledge/question/{question.pk}/','question':f'/question/{question.stable_id}/',
    'original':f'/knowledge/source/{page.image_id}/original/','profile':f'/learning/profile/{learner}/',
    'attempts':[f'/learning/attempt/{row.stable_id}/' for row in attempts]}))
'''

STABLE_CODE = r'''import django,hashlib,json
django.setup()
from django.apps import apps
rows={model._meta.label:list(model.objects.order_by('pk').values())
      for model in apps.get_models() if model.__module__.startswith('app.')}
print(json.dumps({'sha256':hashlib.sha256(json.dumps(rows,sort_keys=True,default=str).encode()).hexdigest(),
    'counts':{key:len(value) for key,value in rows.items()}}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tls-host', choices=('localhost', '127.0.0.1'), default='localhost',
        help='Use 127.0.0.1 to verify IP clients that omit TLS SNI')
    args = parser.parse_args()
    endpoint = os.environ.get('DOCKER_HOST') or base.command([
        'docker', 'context', 'inspect', '--format', '{{.Endpoints.docker.Host}}']).stdout.strip()
    if not endpoint.startswith('unix://'):
        raise RuntimeError('MOB-01 acceptance requires the local Unix-socket Docker daemon')
    owner = 'mobile-' + uuid.uuid4().hex
    project = 'swb-' + owner
    report_dir = ROOT / 'artifacts/mobile-verification' / owner
    report_dir.mkdir(parents=True, mode=0o700)
    report_dir.chmod(0o700)
    (report_dir / 'owner').write_text(owner)
    state = report_dir / 'caddy-state'
    state.mkdir(mode=0o700)
    tag = owner
    image = 'study-workbench:' + tag
    proxy_image = 'study-workbench-caddy:' + tag
    port = base.free_loopback_port()
    env = base.compose_env(owner, tag, base.free_loopback_port(), secrets.token_urlsafe(48), secrets.token_urlsafe(32))
    env.update(SWB_TLS_HOST=args.tls_host, SWB_TLS_BIND_ADDRESS='127.0.0.1', SWB_TLS_HOST_PORT=str(port),
        SWB_PROXY_UID=str(os.getuid()), SWB_PROXY_GID=str(os.getgid()), SWB_CADDY_STATE_DIR=str(state),
        SWB_SOURCE_REVISION='working-tree-mob01')
    origin = f'https://{args.tls_host}:{port}'
    report = {'owner': owner, 'project': project, 'passed': False, 'caddy_image': CADDY_IMAGE,
        'tls_host': args.tls_host, 'remote_36_changed': False,
        'global_trust_changed': False, 'physical_device_tested': False}
    try:
        base.assert_project_absent(project)
        base.assert_image_absent(image)
        base.assert_image_absent(proxy_image)
        for ref in (base.POSTGRES_IMAGE, CADDY_IMAGE):
            base.command(['docker', 'image', 'inspect', ref])  # No registry pulls in acceptance.
        configuration = json.loads(compose(project, env, 'config', '--format', 'json').stdout)
        assert not configuration['services']['web'].get('ports')
        assert not configuration['services']['db'].get('ports')
        assert configuration['services']['caddy']['user'] == f'{os.getuid()}:{os.getgid()}'
        assert configuration['services']['caddy']['ports'][0]['host_ip'] == '127.0.0.1'
        build = compose(project, env, 'build', 'web', 'caddy')
        (report_dir / 'build.log').write_text(build.stdout + build.stderr)
        compose(project, env, 'up', '-d', '--no-build')
        base.wait_compose_health(project, env)
        proxy_state = compose(project, env, 'exec', '-T', 'caddy', 'sh', '-c',
            'id -u; grep CapEff /proc/1/status; getcap /usr/bin/caddy').stdout.splitlines()
        assert proxy_state == [str(os.getuid()), 'CapEff:\t0000000000000000']
        report['proxy_nonroot_and_zero_capabilities'] = True
        ca_file = state / 'caddy/pki/authorities/local/root.crt'
        deadline = time.monotonic() + 45
        while not ca_file.exists():
            if time.monotonic() > deadline: raise RuntimeError('Private CA was not created')
            time.sleep(1)
        report['ca_sha256'] = hashlib.sha256(ca_file.read_bytes()).hexdigest()
        tls = TLSBrowser(origin, ca_file)
        wait_tls(tls)
        try:
            build_opener().open(origin + '/healthz', timeout=5)
        except URLError as error:
            assert isinstance(error.reason, ssl.SSLCertVerificationError)
        else:
            raise RuntimeError('Private test CA unexpectedly trusted globally')
        assert tls.request('/healthz', headers={'X-Forwarded-Proto': 'http'})[0] == 200
        report['tls_checks'] = ['private-ca-verified', 'untrusted-ca-rejected', 'caller-protocol-overwritten', 'web-port-unpublished']
        username, password = 'synthetic-' + owner, secrets.token_urlsafe(24)
        seed = exec_python(project, env, base.SEED_CODE, {'username': username, 'password': password,
            'bundle': json.loads(base.FIXTURE.read_text())})
        assert seed['created']
        form = tls.html('/accounts/login/')[0]
        values = dict(form.hidden, username=username, password=password, next='/')
        from urllib.parse import urlencode
        tls.request('/accounts/login/', data=urlencode(values).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        page_path, preview_path, preview_sha, original_sha = base.upload_from_browser(tls)
        business = exec_python(project, env, (ROOT / 'scripts/container_business_fixture.py').read_text(),
            {'username': username, 'page_id': page_path.split('/')[2]})
        assert business['attempts'] == 3 and business['model_disabled']
        routes = exec_python(project, env, LINK_CODE, {'username': username, 'page_id': page_path.split('/')[2]})
        routes.update(page=page_path, preview=preview_path, assessment=f'/learning/assessment/{business["assessment"]}/')
        before = exec_python(project, env, STABLE_CODE)
        files_before = exec_python(project, env, base.SNAPSHOT_CODE)['asset_files']
        nss = report_dir / 'nssdb'
        nss.mkdir(mode=0o700)
        base.command(['certutil', '-N', '-d', 'sql:' + str(nss), '--empty-password'])
        base.command(['certutil', '-A', '-d', 'sql:' + str(nss), '-n', owner, '-t', 'C,,', '-i', str(ca_file)])
        config_path = report_dir / 'browser.local.json'
        config_path.write_text(json.dumps({'owner': owner, 'origin': origin, 'username': username, 'password': password,
            'routes': routes, 'preview_sha256': preview_sha, 'original_sha256': original_sha}))
        config_path.chmod(0o600)
        browser_env = dict(os.environ)
        temp = report_dir / 'browser-tmp'
        temp.mkdir(mode=0o700)
        browser_cache = Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')).resolve()
        if not os.environ.get('PLAYWRIGHT_BROWSERS_PATH') or not browser_cache.is_dir():
            raise RuntimeError('Set the already-cached PLAYWRIGHT_BROWSERS_PATH explicitly')
        # Overlay only the NSS directories in a disposable mount namespace; never change HOME or global trust.
        browser_run = base.command(['sudo', '-n', '--preserve-env=HOME,PLAYWRIGHT_BROWSERS_PATH,TMPDIR',
            'bwrap', '--die-with-parent', '--unshare-pid', '--ro-bind', '/', '/', '--dev-bind', '/dev', '/dev',
            '--proc', '/proc', '--bind', str(report_dir), str(report_dir),
            '--bind', str(temp), '/tmp', '--ro-bind', str(browser_cache), '/opt',
            '--setenv', 'TMPDIR', '/tmp', '--setenv', 'PLAYWRIGHT_BROWSERS_PATH', '/opt',
            '--bind', str(nss), str(Path.home() / '.pki/nssdb'),
            '--bind', str(nss), str(Path.home() / '.local/share/pki/nssdb'),
            '--', 'setpriv', f'--reuid={os.getuid()}', f'--regid={os.getgid()}', '--init-groups',
            sys.executable, str(ROOT / 'scripts/verify_mobile_browser.py'), str(config_path)], env=browser_env)
        (report_dir / 'browser.log').write_text(browser_run.stdout + browser_run.stderr)
        after = exec_python(project, env, STABLE_CODE)
        assert after == before
        assert exec_python(project, env, base.SNAPSHOT_CODE)['asset_files'] == files_before
        compose(project, env, 'up', '-d', '--no-build', '--force-recreate', 'web', 'caddy')
        base.wait_compose_health(project, env)
        assert exec_python(project, env, STABLE_CODE) == before
        assert exec_python(project, env, base.SNAPSHOT_CODE)['asset_files'] == files_before
        assert hashlib.sha256(ca_file.read_bytes()).hexdigest() == report['ca_sha256']
        wait_tls(tls)
        base.verify_preview(tls, preview_path, preview_sha)
        report.update(passed=True, original_sha256=original_sha, private_files=len(files_before),
            app_records_unchanged=True, recreate_preserved_data_and_ca=True,
            browser=json.loads((report_dir / 'browser-report.local.json').read_text()))
        print(json.dumps({'passed': True, 'report': str(report_dir.relative_to(ROOT)),
            'browser_checks':len(report['browser']['checks']), 'private_files':len(files_before)}, ensure_ascii=False), flush=True)
    finally:
        base.cleanup_project(project, owner, env)
        base.assert_project_absent(project)
        for owned_image in (image, proxy_image):
            inspection = base.command(['docker', 'image', 'inspect', owned_image], check=False)
            if inspection.returncode == 0:
                details = json.loads(inspection.stdout)[0]
                if details['Config']['Labels'].get('com.study-workbench.resource-owner') == owner:
                    base.command(['docker', 'image', 'rm', owned_image])
        report['owned_resources_removed'] = True
        (report_dir / 'verification.local.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
