#!/usr/bin/env python3
"""Trusted Chromium acceptance, invoked by verify_mobile.py in a private mount namespace."""
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright, expect


ROOT = Path(__file__).resolve().parents[1]


def verify(config_path):
    path = Path(config_path).resolve()
    if (path.parent.parent != ROOT / 'artifacts/mobile-verification'
            or path.name != 'browser.local.json' or path.stat().st_mode & 0o077):
        raise RuntimeError('Requires the protected, owned mobile acceptance configuration')
    config = json.loads(path.read_text())
    origin = config['origin']
    if (urlsplit(origin).scheme != 'https' or urlsplit(origin).hostname not in ('localhost', '127.0.0.1')
            or not config['owner'] or (path.parent / 'owner').read_text() != config['owner']):
        raise RuntimeError('Only the owned loopback synthetic HTTPS instance is accepted')
    checks, errors, outside = [], [], []
    # Playwright's request client runs in Node, whose trust store differs from Chromium's NSS.
    ca_file = path.parent / 'caddy-state/caddy/pki/authorities/local/root.crt'
    if not ca_file.is_file(): raise RuntimeError('The owned private CA is missing')
    os.environ['NODE_EXTRA_CA_CERTS'] = str(ca_file)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 390, 'height': 844},
            is_mobile=True, has_touch=True, device_scale_factor=2)
        context.on('request', lambda request: outside.append(request.url)
            if urlsplit(request.url).scheme in ('http', 'https') and not request.url.startswith(origin + '/') else None)
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(origin + '/accounts/login/')
        expect(page.locator('h1')).to_have_text('登录')
        response = context.request.get(origin + '/healthz')
        assert response.status == 200  # No certificate-error overrides in browser or request context.
        checks.append('trusted-tls-without-certificate-bypass')
        page.wait_for_function('navigator.serviceWorker.controller !== null')
        expect(page.locator('#pwa-network-status')).to_be_hidden()
        page.locator('#id_username').fill(config['username'])
        page.locator('#id_password').fill(config['password'])
        page.locator('button[type=submit]').click()
        expect(page).to_have_url(origin + '/')
        cookies = {item['name']: item for item in context.cookies()}
        assert cookies['sessionid']['secure'] and cookies['sessionid']['httpOnly']
        assert cookies['csrftoken']['secure']
        assert context.request.post(origin + '/accounts/logout/').status == 403
        checks.append('secure-session-and-csrf-required')
        manifest = context.request.get(origin + '/manifest.webmanifest').json()
        assert manifest['id'] == '/' and manifest['start_url'] == '/' and manifest['display'] == 'standalone'
        for icon in manifest['icons']:
            icon_response = context.request.get(origin + icon['src'])
            assert icon_response.status == 200 and icon_response.body().startswith(b'\x89PNG')
        session = context.new_cdp_session(page)
        installability = session.send('Page.getInstallabilityErrors')['installabilityErrors']
        assert not installability, installability
        checks.append('manifest-icons-and-chromium-installability')

        routes = config['routes']
        page.goto(origin + routes['node'])
        expect(page.locator(f'a[href="{routes["knowledge_question"]}"]').first).to_be_visible()
        page.goto(origin + routes['knowledge_question'])
        expect(page.locator(f'a[href="{routes["node"]}"]').first).to_be_visible()
        assert '4 × 2 = ?' in page.locator('body').inner_text()
        page.goto(origin + routes['page'])
        expect(page.locator(f'a[href="{routes["question"]}"]').first).to_be_visible()
        preview = context.request.get(origin + routes['preview'])
        assert preview.status == 200 and 'no-store' in preview.headers['cache-control']
        assert hashlib.sha256(preview.body()).hexdigest() == config['preview_sha256']
        original = context.request.get(origin + routes['original'])
        assert original.status == 200 and 'no-store' in original.headers['cache-control']
        assert hashlib.sha256(original.body()).hexdigest() == config['original_sha256']
        checks.append('knowledge-question-original-bidirectional-and-exact-bytes')
        page.goto(origin + routes['profile'])
        for route in routes['attempts']:
            expect(page.locator(f'a[href="{route}"]').first).to_be_visible()
            page.goto(origin + route)
            assert '来源' in page.locator('body').inner_text()
            page.goto(origin + routes['profile'])
        assert all(text in page.locator('body').inner_text() for text in ('课堂', '提示', '独立'))
        page.goto(origin + routes['assessment'])
        checks.append('three-separate-attempts-and-assessment-readable')

        cache_entries = lambda: page.evaluate('''async () => {
            const entries = {};
            for (const name of await caches.keys()) {
                const cache = await caches.open(name);
                entries[name] = (await cache.keys()).map(request => request.url);
            }
            return entries;
        }''')
        entries = cache_entries()
        assert len(entries) == 1 and next(iter(entries)).startswith('study-workbench-offline-')
        urls = next(iter(entries.values()))
        assert len(urls) == 1 and '/static/web/pwa/offline.' in urls[0]
        offline_body = page.evaluate('async url => (await (await caches.match(url)).text())', urls[0])
        assert config['username'] not in offline_body and '没有缓存学习资料' in offline_body
        checks.append('cache-storage-holds-only-public-generic-offline-page')
        await_update = page.evaluate('async () => { const reg = await navigator.serviceWorker.ready; await reg.update(); return reg.scope; }')
        assert await_update == origin + '/'
        # Reinstallation exercises activation cleanup while unrelated origin caches survive.
        page.evaluate('''async () => {
            await (await navigator.serviceWorker.ready).unregister();
            await caches.open('study-workbench-offline-old-canary');
            await caches.open('unrelated-public-canary');
        }''')
        page.reload()
        page.wait_for_function('''async () => (await navigator.serviceWorker.getRegistration())?.active &&
            !(await caches.keys()).includes('study-workbench-offline-old-canary')''')
        assert 'unrelated-public-canary' in cache_entries()
        page.evaluate("caches.delete('unrelated-public-canary')")
        checks.append('worker-revalidation-and-owned-old-cache-cleanup')
        context.set_offline(True)
        page.goto(origin + routes['profile'])
        expect(page.locator('h1')).to_have_text('暂时无法连接工作台')
        assert '合成学习者' not in page.locator('body').inner_text()
        page.screenshot(path=str(path.parent / 'phone-offline.png'), full_page=True)
        context.set_offline(False)
        page.goto(origin + '/mobile/')
        expect(page.locator('h1')).to_have_text('在手机上打开工作台')
        page.screenshot(path=str(path.parent / 'phone-mobile-help.png'), full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        checks.append('offline-navigation-is-generic-and-online-recovery')
        page.locator('.logout-form button').click()
        expect(page).to_have_url(origin + '/accounts/login/')
        private_response = context.request.get(origin + routes['preview'], max_redirects=0)
        assert private_response.status == 302 and 'no-store' in private_response.headers['cache-control']
        page.goto(origin + routes['profile'])
        expect(page).to_have_url(origin + '/accounts/login/?next=' + routes['profile'])
        assert len(cache_entries()) == 1 and urls == next(iter(cache_entries().values()))
        checks.append('logout-and-private-reread-rejected-without-private-cache')
        assert not errors and not outside
        report = {'passed': True, 'checks': checks, 'browser': browser.version,
            'javascript_errors': errors, 'outside_requests': outside, 'cache_entries': entries,
            'certificate_validation_bypassed': False, 'physical_device_tested': False,
            'certificate_validation_methods': ['Chromium private NSS', 'Node process extra CA'],
            'actual_home_screen_install_tested': False}
        context.close()
        browser.close()
    (path.parent / 'browser-report.local.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'browser_checks': len(checks), 'passed': True}, ensure_ascii=False))


if __name__ == '__main__':
    verify(sys.argv[1])
