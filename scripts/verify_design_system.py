"""Design contract checks against the owned synthetic PC browser only."""
import json
import re
from urllib.parse import parse_qs, urlencode, urlparse


def verify(page, origin, app_url, output, checks):
    from playwright.sync_api import expect

    def settle_theme():
        page.evaluate("""async () => {
            await new Promise(resolve => requestAnimationFrame(resolve));
            await Promise.all(document.getAnimations({subtree:true})
                .filter(animation => animation.playState === 'running')
                .map(animation => animation.finished.catch(() => {})));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }""")
        expect(page.get_by_text(re.compile(r'^(正在读取|正在整理|正在加载)')).filter(visible=True)).to_have_count(0)

    measurements = []
    page.set_viewport_size({'width': 1440, 'height': 1000})
    for view in ('overview', 'materials', 'knowledge', 'learning', 'progress', 'documents', 'settings'):
        page.goto(origin + app_url(view=view))
        expect(page.locator('#content h1').first).to_be_visible()
        if view == 'overview':
            expect(page.get_by_role('heading', name='当前范围摘要', exact=True)).to_be_visible()
            expect(page.get_by_role('region', name='接下来做什么', exact=True).get_by_role('link').first).to_be_visible()
        expect(page.get_by_text(re.compile(r'^(正在读取|正在整理|正在加载)')).filter(visible=True)).to_have_count(0)
        page.evaluate('''async () => {
            await document.fonts.ready;
            const images = [...document.querySelectorAll('#content img')].filter(image => image.getClientRects().length);
            await Promise.all(images.map(image => {
                image.loading = 'eager';
                if (image.complete) { if (!image.naturalWidth) throw new Error('Broken visible image'); return; }
                return new Promise((resolve, reject) => {
                    image.addEventListener('load', resolve, {once:true});
                    image.addEventListener('error', reject, {once:true});
                });
            }));
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
        }''')
        for theme in ('light', 'dark'):
            page.evaluate('(theme) => document.documentElement.classList.toggle("dark", theme === "dark")', theme)
            settle_theme()
            data = page.evaluate('''() => {
                const root = getComputedStyle(document.documentElement), main = document.querySelector('#content');
                const heading = main.querySelector('h1'), mainStyle = getComputedStyle(main);
                const color = value => {
                    const probe = document.createElement('span'); probe.style.color = value;
                    document.body.append(probe); const result = getComputedStyle(probe).color; probe.remove(); return result;
                };
                const dark = document.documentElement.classList.contains('dark');
                return {theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
                    foreground: root.getPropertyValue('--foreground').trim(),
                    primary: color(root.getPropertyValue('--primary').trim()),
                    expectedPrimary: color(dark ? 'oklch(0.929 0.013 255.508)' : 'oklch(0.208 0.042 265.755)'),
                    statusSuccess: color(root.getPropertyValue('--status-success').trim()),
                    expectedSuccess: color(dark ? '#052e16' : '#f0fdf4'),
                    font: getComputedStyle(document.body).fontFamily,
                    headingSize: getComputedStyle(heading).fontSize,
                    mainWidth: main.getBoundingClientRect().width, maximum: parseFloat(mainStyle.maxWidth),
                    scrollWidth: document.documentElement.scrollWidth, viewport: innerWidth};
            }''')
            assert data['headingSize'] == '24px', (view, theme, data)
            assert data['statusSuccess'] == data['expectedSuccess'], data
            assert data['primary'] == data['expectedPrimary'], data
            assert 'system-ui' in data['font'], data
            assert data['maximum'] == (1056 if view == 'settings' else 1440), data
            assert data['mainWidth'] <= data['maximum'] + 1, data
            assert data['scrollWidth'] <= data['viewport'] + 2, (view, data)
            if view == 'settings':
                button = page.locator('#members-panel-create > summary')
                expect(button).to_be_visible()
                primary = button.evaluate('''element => {
                    const probe = document.createElement('span');
                    const canonical = value => {
                        probe.style.color = value; document.body.append(probe);
                        const result = getComputedStyle(probe).color; probe.remove(); return result;
                    };
                    const root = getComputedStyle(document.documentElement), style = getComputedStyle(element);
                    return {text: style.color, background: style.backgroundColor, height: element.getBoundingClientRect().height,
                        expectedText: canonical(root.getPropertyValue('--primary-foreground').trim()),
                        expectedBackground: canonical(root.getPropertyValue('--primary').trim())};
                }''')
                assert primary['text'] == primary['expectedText'] and primary['background'] == primary['expectedBackground'], primary
                assert primary['height'] >= 44, primary
                data['memberAction'] = primary
            measurements.append({'view': view, **data})
            page.screenshot(path=str(output / f'design-{view}-1440-{theme}.png'), full_page=True)
        checks.append(f'design-contract-{view}-1440-light-dark')
    page.evaluate('document.documentElement.classList.remove("dark")')
    # The compatibility page loads app.css directly, not the React frame CSS.
    household = parse_qs(urlparse(app_url(view='settings')).query)['household'][0]
    page.goto(origin + '/members/?' + urlencode({'household_id': household}))
    expect(page.get_by_role('heading', name='家庭成员', exact=True)).to_be_visible()
    page.locator('#members-panel-create > summary').click()
    for theme in ('light', 'dark'):
        page.evaluate('(theme) => document.documentElement.classList.toggle("dark", theme === "dark")', theme)
        settle_theme()
        data = page.evaluate('''() => {
            const root = getComputedStyle(document.documentElement);
            const color = value => {
                const probe = document.createElement('span'); probe.style.color = value;
                document.body.append(probe); const result = getComputedStyle(probe).color; probe.remove(); return result;
            };
            const primary = [...document.querySelectorAll('.primary-button')].find(e => e.getClientRects().length);
            const input = [...document.querySelectorAll('.field input:not([type=hidden])')].find(e => e.getClientRects().length);
            if (!primary || !input) throw new Error('Expected actual visible member form controls');
            return {theme: document.documentElement.classList.contains('dark') ? 'dark' : 'light',
                primaryText: getComputedStyle(primary).color,
                primaryBackground: getComputedStyle(primary).backgroundColor,
                primaryHeight: primary.getBoundingClientRect().height,
                inputBackground: getComputedStyle(input).backgroundColor,
                expectedText: color(root.getPropertyValue('--primary-foreground').trim()),
                expectedBackground: color(root.getPropertyValue('--primary').trim()),
                expectedInput: color(root.getPropertyValue('--background').trim())};
        }''')
        assert data['primaryText'] == data['expectedText'], data
        assert data['primaryBackground'] == data['expectedBackground'], data
        assert data['inputBackground'] == data['expectedInput'], data
        assert data['primaryHeight'] >= 44, data
        measurements.append({'view': 'native-members', **data})
        page.screenshot(path=str(output / f'design-native-members-1440-{theme}.png'), full_page=True)
    checks.append('design-contract-native-members-1440-light-dark')
    page.evaluate('document.documentElement.classList.remove("dark")')
    (output / 'design-system.local.json').write_text(json.dumps(measurements, ensure_ascii=False, indent=2))
