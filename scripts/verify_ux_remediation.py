"""Additional UX acceptance, only called inside the owned synthetic PC run."""
from io import BytesIO
import json
import hashlib
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlencode
from uuid import uuid4


def verify(page, origin, app_url, db, actor, house, material, fixture, output, checks):
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.urls import reverse
    from app.web import services as materials
    from app.web.models import QuestionSource
    from PIL import Image, ImageDraw, ImageGrab
    from playwright.sync_api import expect

    def create_portrait():
        row = materials.create_material(actor, house.pk, 'UX 合成竖版来源', uuid4().hex)
        image = Image.new('RGB', (2048, 3072), 'white')
        draw = ImageDraw.Draw(image)
        draw.rectangle((400, 600, 1400, 1800), outline='black', width=12)
        stream = BytesIO(); image.save(stream, format='PNG')
        saved = materials.upload_page(actor, row.pk, SimpleUploadedFile('ux-synthetic.png',
            stream.getvalue(), content_type='image/png'), uuid4().hex)
        return row, saved['page_id']

    portrait, page_id = db(create_portrait)
    def original_digest():
        from app.web.models import MaterialPage
        image=MaterialPage.objects.select_related('image').get(pk=page_id).image
        return hashlib.sha256(materials.asset_path(image.payload['storage_key'],image.sha256).read_bytes()).hexdigest()
    original_hash=db(original_digest)
    measurements = []
    def settle():
        expect(page.locator('#content')).to_be_visible()
        page.evaluate("[...document.images].filter(i => i.getClientRects().length).forEach(i => {i.loading='eager'})")
        page.wait_for_function("[...document.images].filter(i => i.getClientRects().length).every(i => i.complete && i.naturalWidth)")
        for label in ('正在整理学习证据…', '正在读取计划…', '正在读取家庭资料…'):
            expect(page.get_by_text(label, exact=True).filter(visible=True)).to_have_count(0)
    def no_overflow(label):
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 2'), label
    def check_saved_overlay(box, image, geometry):
        expect(box).to_be_visible(); settle()
        rect=image.bounding_box(); overlay=box.bounding_box(); assert rect and overlay
        x0,y0,x1,y1=geometry
        expected=[rect['x']+x0*rect['width']/2048,rect['y']+y0*rect['height']/3072,
                  (x1-x0)*rect['width']/2048,(y1-y0)*rect['height']/3072]
        actual=[overlay[key] for key in ('x','y','width','height')]
        assert all(abs(a-b)<=2 for a,b in zip(actual,expected)),(actual,expected)
    accept = lambda dialog: dialog.accept()
    page.on('dialog', accept)
    complete=False
    try:
        for kind, path in [('question', reverse('web:question_new', args=[portrait.pk])),
                           ('knowledge', reverse('knowledge:node_new', args=['knowledge']) + '?' + urlencode({'household_id': house.pk})),
                           ('observation', reverse('learning:observation_new') + '?' + urlencode({'household': house.pk}))]:
            for width in (1280, 1440, 1920):
                page.set_viewport_size({'width': width, 'height': 1000})
                page.goto(origin + app_url(path, view={'question':'materials', 'knowledge':'knowledge', 'observation':'learning'}[kind]))
                card = page.locator(f'.region-card[data-page-id="{page_id}"]')
                expect(card.locator('.region-image')).to_be_visible()
                expect(card.locator('.region-zoom-in')).to_be_visible()
                settle(); no_overflow((kind, width))
                rects = card.evaluate('''card => {
                    const image=card.querySelector('.region-image').getBoundingClientRect();
                    const canvas=card.querySelector('.region-canvas').getBoundingClientRect();
                    return {image:[image.x,image.y,image.width,image.height],canvas:[canvas.x,canvas.y,canvas.width,canvas.height]};
                }''')
                assert all(abs(a-b) <= 1 for a,b in zip(rects['image'],rects['canvas'])), rects
                measurements.append({'kind':kind,'width':width,**rects})
                page.screenshot(path=str(output / f'ux-source-{kind}-{width}.png'), full_page=True)
            # Zoom and rotate before saving: coordinates must refer to displayed pixels,
            # and saved original coordinates must be traceable to this exact preview.
            card.locator('.rotation-select').select_option('90')
            page.wait_for_function("id => {const c=document.querySelector(`.region-card[data-page-id='${id}']`);return c.dataset.rotation==='90' && c.querySelector('img').complete}", arg=page_id)
            card.locator('.region-zoom-in').click()
            card.locator('.region-select-mode').click()
            canvas = card.locator('.region-canvas'); canvas.scroll_into_view_if_needed()
            viewport = card.locator('.region-viewport').bounding_box(); assert viewport
            stage = canvas.bounding_box(); assert stage
            start=(viewport['x']+viewport['width']*.2, viewport['y']+viewport['height']*.2)
            end=(viewport['x']+viewport['width']*.55, viewport['y']+viewport['height']*.45)
            page.mouse.move(*start); page.mouse.down(); page.mouse.move(*end,steps=5); page.mouse.up()
            add = card.locator('.add-region'); expect(add).to_be_enabled(); add.click()
            sources=json.loads(page.locator('#id_sources').input_value())
            source=next(row for row in sources if row['page_id']==page_id)
            expected=[round((x-stage['x'])*3072/stage['width']) for x in (start[0],end[0])]
            expected_y=[round((y-stage['y'])*2048/stage['height']) for y in (start[1],end[1])]
            assert all(abs(a-b)<=3 for a,b in zip(source['display_bbox'],[expected[0],expected_y[0],expected[1],expected_y[1]])), source
            if kind=='question':
                page.locator('#id_original_number').fill('UX-source')
                page.locator('#id_printed_text').fill('合成题干：2 + 3 = ?')
                page.locator('#id_reason').fill('合成大图旋转缩放坐标验收')
                with page.expect_response(lambda response: '/workspace/submit/' in response.url and response.request.method=='POST') as saved:
                    page.locator('button[value="draft"]').click()
                assert saved.value.status==200, saved.value.status
                stored=db(lambda: QuestionSource.objects.filter(material=portrait,original_number='UX-source').latest('pk').sources)
                assert stored[0]['display_bbox']==source['display_bbox']
                assert stored[0]['original_bbox']!=stored[0]['display_bbox']
                assert stored[0]['rotation']==90
                question_id=db(lambda: QuestionSource.objects.filter(material=portrait,original_number='UX-source').latest('pk').revision.entity.stable_id)
                page.goto(origin+app_url(reverse('web:question_edit',args=[question_id]),view='materials'))
                expect(page.locator('#id_printed_text')).to_have_value('合成题干：2 + 3 = ?')
                restored=json.loads(page.locator('#id_sources').input_value())
                assert restored[0]['display_bbox']==source['display_bbox']
            elif kind=='knowledge':
                page.locator('#id_definition').fill('分数相加\n1/2 + 1/3')
                page.get_by_role('textbox',name='公式辅助').fill('1/2 + 1/3')
                page.get_by_role('button',name='预览公式',exact=True).click()
                expect(page.get_by_role('button',name='加入定义与排版',exact=True)).to_be_visible()
                page.get_by_role('button',name='加入定义与排版',exact=True).click()
                expect(page.locator('#id_display_markup')).to_have_value('分数相加\n[[math:1/2 + 1/3]]')
                page.locator('#id_reason').fill('合成公式、来源与排版验收')
                page.get_by_role('button',name='保存为待审核草稿',exact=True).click()
                expect(page.locator('#id_definition')).to_have_count(0)
                expect(page.locator('.workspace-page')).to_contain_text('分数相加')
                expect(page.locator('.workspace-page h1')).to_be_visible()
                assert not page.locator('.errorlist').count(), page.locator('.workspace-page').inner_text()
                screen=page.evaluate("new URLSearchParams(location.search).get('screen')")
                node_id=screen.rstrip('/').split('/')[-1]
                from app.web import knowledge_services as knowledge
                geometry=db(lambda: knowledge.node_detail(actor,node_id)['current_sources'][0]['geometry'])
                x0,y0,x1,y1=source['display_bbox']
                assert list(geometry)==[y0,3072-x1,y1,3072-x0]
                page.goto(origin+app_url(reverse('knowledge:node_edit',args=[node_id]),view='knowledge'))
                # The edit form appends newly selected sources. Existing exact
                # references reopen separately instead of being duplicated.
                assert json.loads(page.locator('#id_sources').input_value())==[]
                expect(page.locator('#id_replace_sources')).not_to_be_checked()
                check_saved_overlay(page.locator('.evidence-box').first,
                    page.locator('.evidence-preview img').first,geometry)
                expect(page.locator('#id_display_markup')).to_have_value('分数相加\n[[math:1/2 + 1/3]]')
                page.screenshot(path=str(output/'ux-knowledge-saved-region.png'),full_page=True)
            else:
                page.locator('#id_notes').fill('合成来源观察：作者及日期仍未知')
                page.locator('#id_reason').fill('合成竖版旋转选区验收')
                page.get_by_role('button',name='保存来源观察',exact=True).click()
                expect(page.locator('#learning-observation-form')).to_have_count(0)
                screen=page.evaluate("new URLSearchParams(location.search).get('screen')")
                observation_id=screen.rstrip('/').split('/')[-1]
                from app.web import learning_services as learning
                def geometry():
                    data=learning.observation_edit_context(actor,observation_id)
                    revision=data['observation'].revisions[-1]
                    assert revision.author_state.value=='unknown'
                    assert revision.actual_date_state.value=='unknown'
                    ref=revision.evidence_refs[0]
                    return next(region.geometry for region in data['bundle'].regions if region.header.revision_id==ref.region_revision_id)
                x0,y0,x1,y1=source['display_bbox']
                assert list(db(geometry))==[y0,3072-x1,y1,3072-x0]
                page.reload()
                check_saved_overlay(page.locator('.history-region-box').first,
                    page.locator('.history-image-wrap img').first,[y0,3072-x1,y1,3072-x0])
                page.screenshot(path=str(output/'ux-observation-saved-region.png'),full_page=True)
            checks.append(f'ux-large-source-{kind}-three-widths-zoom-rotation-save-reopen')

        assert db(original_digest)==original_hash
        checks.append('ux-source-original-bytes-unchanged')

        for width in (1280,1440,1920):
            page.set_viewport_size({'width':width,'height':1000})
            for view in ('overview','materials','knowledge','learning','progress','documents','settings'):
                page.goto(origin+app_url(view=view)+'&learner='+fixture['learner']+('&material='+str(material.pk) if view=='materials' else ''))
                if view in ('materials','documents'): expect(page.get_by_role('heading',name=material.title,exact=True)).to_be_visible()
                elif view=='overview': expect(page.get_by_role('heading',name='当前范围摘要',exact=True)).to_be_visible()
                elif view=='progress': expect(page.get_by_role('heading',name='复测计划',exact=True)).to_be_visible()
                else: expect(page.locator('.workspace-page h1')).to_be_visible()
                settle(); no_overflow((view,width))
                page.screenshot(path=str(output/f'ux-final-{view}-{width}.png'),full_page=True)
        checks.append('ux-final-seven-domains-1280-1440-1920')

        page.goto(origin+app_url(view='overview')+'&learner='+fixture['learner']+'&date_from=2099-01-01')
        expect(page.get_by_text('当前筛选范围没有作答记录',exact=True)).to_be_visible()
        assert not page.get_by_text('还没有作答记录',exact=True).count()
        page.get_by_role('button',name='查看全部作答记录',exact=True).click()
        expect(page.get_by_role('heading',name='近期作答记录',exact=True)).to_be_visible()
        page.go_back(); expect(page.get_by_text('当前筛选范围没有作答记录',exact=True)).to_be_visible()
        page.reload(); expect(page.get_by_label('实际作答日期起')).to_have_value('2099-01-01')
        checks.append('ux-filter-zero-clear-browser-back-and-refresh')

        page.goto(origin+app_url(view='progress')+'&tab=materials')
        expect(page.get_by_role('button',name='返回资料整理',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='资料进度',exact=True)).to_be_visible()
        expect(page.get_by_role('navigation',name='主导航').get_by_role('button',name='资料整理',exact=True)).to_have_attribute('aria-current','page')
        expect(page.get_by_label('家庭',exact=True)).to_have_value(house.pk)
        page.reload()
        expect(page.get_by_role('button',name='返回资料整理',exact=True)).to_be_visible()
        expect(page.get_by_role('heading',name='资料进度',exact=True)).to_be_visible()
        page.get_by_role('button',name='返回资料整理',exact=True).click()
        assert 'view=materials' in page.url
        expect(page.get_by_role('region',name='资料列表',exact=True)).to_be_visible()
        checks.append('ux-processing-migration-old-link-return')

        # Actual native browser zoom, dispatched to the private headed browser window.
        tool=os.environ.get('SWB_UX_XDOTOOL')
        if tool:
            page.bring_to_front()
            windows=subprocess.check_output([tool,'search','--onlyvisible','--class','chromium'],text=True).split()
            assert windows
            subprocess.run([tool,'windowfocus','--sync',windows[-1]],check=True)
            subprocess.run([tool,'key','--clearmodifiers','ctrl+0'],check=True)
            for _ in range(5): subprocess.run([tool,'key','--clearmodifiers','ctrl+plus'],check=True)
            time.sleep(.3)
            zoom=page.evaluate('({ratio:devicePixelRatio,width:innerWidth})')
            assert zoom['ratio']>=1.9, zoom
            for view in ('overview','materials','knowledge','learning','progress','documents','settings'):
                page.goto(origin+app_url(view=view)+'&learner='+fixture['learner']+('&material='+str(material.pk) if view=='materials' else ''))
                if view=='overview': expect(page.get_by_role('heading',name='当前范围摘要',exact=True)).to_be_visible()
                elif view in ('materials','documents'): expect(page.get_by_role('heading',name=material.title,exact=True)).to_be_visible()
                elif view=='progress': expect(page.get_by_role('heading',name='复测计划',exact=True)).to_be_visible()
                else: expect(page.locator('.workspace-page h1')).to_be_visible()
                settle(); no_overflow(('native-200-percent',view))
                page.keyboard.press('Tab')
                assert page.evaluate('document.activeElement !== document.body'), view
                # Chromium's full-page capture crops native-zoom pixels to CSS
                # dimensions and briefly changes the painted viewport. Capture
                # the owned display directly after the focus/layout has painted.
                page.evaluate('async () => {await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))}')
                time.sleep(.15)
                assert os.environ.get('SWB_PC_HEADED') == '1'
                display = ImageGrab.grab(xdisplay=os.environ['DISPLAY'])
                assert display.width >= 1900 and display.height >= 1000
                display.save(output/f'ux-200-display-{view}.png')
            subprocess.run([tool,'key','--clearmodifiers','ctrl+0'],check=True)
            measurements.append({'native_browser_zoom':zoom})
            checks.append('ux-native-browser-200-percent-seven-domains-keyboard')
        complete=True
    finally:
        (output/'ux-remediation.local.json').write_text(json.dumps({'status':'passed' if complete else 'incomplete','measurements':measurements,'checks':checks},ensure_ascii=False,indent=2))
        page.remove_listener('dialog',accept)
