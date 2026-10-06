"""Follow-up acceptance inside the existing owned synthetic PC environment."""
import hashlib
import json
import os
import subprocess
from urllib.parse import urlencode


def verify(page, origin, app_url, db, actor, house, material, fixture, output, checks):
    from playwright.sync_api import expect
    from app.persistence.models import EntityRecord
    from app.web import learning_services
    from app.printing.models import ExportSnapshot
    from app.printing import services as printing

    # Continue the complete keyboard task at actual native zoom, rather than
    # counting a single Tab on each page as a completed 200% task.
    tool = os.environ.get('SWB_UX_XDOTOOL')
    native_zoom = None
    if tool:
        assert os.environ.get('SWB_PC_HEADED') == '1'
        page.bring_to_front()
        windows = subprocess.check_output([tool, 'search', '--onlyvisible', '--class', 'chromium'], text=True).split()
        assert windows
        subprocess.run([tool, 'windowfocus', '--sync', windows[-1]], check=True)
        subprocess.run([tool, 'key', '--clearmodifiers', 'ctrl+0'], check=True)
        for _ in range(5):
            subprocess.run([tool, 'key', '--clearmodifiers', 'ctrl+plus'], check=True)
        page.wait_for_function('devicePixelRatio >= 1.9')
        native_zoom = page.evaluate('({ratio:devicePixelRatio,width:innerWidth})')

    def capture_task(name):
        if tool:
            from PIL import ImageGrab
            page.evaluate('async () => {await document.fonts.ready; await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))}')
            display = ImageGrab.grab(xdisplay=os.environ['DISPLAY'])
            assert display.width >= 1900 and display.height >= 1000
            display.save(output / f'follow-up-200-{name}.png')

    learner = fixture['learner']
    overview = origin + app_url(view='overview') + '&learner=' + learner
    page.goto(overview)
    expect(page.locator('#learning-tasks-title')).to_have_count(1)
    choices = page.get_by_label('学习者', exact=True)
    values = choices.locator('option').evaluate_all('items => items.map(item => item.value).filter(Boolean)')
    if len(values) > 1:
        for value in (values[1], values[0], values[1], values[0]):
            choices.select_option(value)
            expect(page.locator('#learning-tasks-title')).to_have_count(1)
            expect(page.get_by_role('heading', name='当前范围摘要', exact=True)).to_be_visible()
    for view in ('materials', 'knowledge', 'learning', 'progress', 'documents', 'settings'):
        page.goto(origin + app_url(view=view) + '&learner=' + learner)
        expect(page.locator('main')).to_be_visible()
        expect(page.locator('#learning-tasks-title')).to_have_count(0)
    page.goto(overview)
    expect(page.locator('#learning-tasks-title')).to_have_count(1)
    checks.append('follow-up-single-action-region-learner-switch-and-six-other-domains')

    parent = page.get_by_role('button', name='家长跟进', exact=True)
    parent.press('Enter')
    expect(parent).to_have_attribute('aria-pressed', 'true')
    page.reload()
    expect(page.get_by_role('button', name='家长跟进', exact=True)).to_have_attribute('aria-pressed', 'true')
    page.get_by_role('button', name='学生练习', exact=True).press('Enter')
    page.get_by_role('navigation', name='主导航').get_by_role('button', name='知识与题库', exact=True).press('Enter')
    page.wait_for_function("() => new URLSearchParams(location.search).get('screen')?.includes('mode=learn')")
    checks.append('follow-up-mode-keyboard-account-preference-and-practice-default')

    question_pk = db(lambda: EntityRecord.objects.get(household=house, kind='question', stable_id=fixture['question']).pk)
    question_row = page.locator(f'tr[data-row-href="/knowledge/question/{question_pk}/"]')
    expect(question_row).to_be_visible()
    question_row.focus(); question_row.press('Enter')
    expect(page.get_by_role('region', name='练习任务', exact=True)).to_be_visible()
    help_summary = page.locator('summary').filter(has_text='需要帮助时查看知识与方法')
    answer_summary = page.locator('summary').filter(has_text='查看家长参考答案（完成尝试后再打开）')
    for summary in (help_summary, answer_summary):
        expect(summary).to_be_visible()
        assert not summary.evaluate('(summary) => summary.parentElement.open')
        summary.focus(); summary.press('Enter')
        expect(summary.locator('..').locator('.disclosure-content')).to_be_visible()
        assert summary.evaluate('(summary) => summary.parentElement.open')
        capture_task('question-help' if summary is help_summary else 'question-parent-answer')
        summary.press('Enter')
        assert not summary.evaluate('(summary) => summary.parentElement.open')
    checks.append('follow-up-native-question-row-keyboard-explicit-help-and-answer-disclosures')

    # Start a real plan, save a new event, then confirm its exact revision.
    from app.study import services as study
    from app.study.models import ScheduleRevision, StudySchedule
    from uuid import uuid4
    def make_plan():
        context = study.new_schedule_context(actor, fixture['learner_entity'])
        question = EntityRecord.objects.get(household=house, kind='question', stable_id=fixture['question'])
        return study.create_schedule(actor, fixture['learner_entity'], question_revision_id=question.published_revision_id,
            due_date='2026-10-07', goal='合成连续复测验收', prompt_plan='先自主完成', reason='受控合成任务', context=context['context'], request_key=uuid4().hex)
    plan = db(make_plan)
    page.goto(origin + app_url(f'/study/schedule/{plan["schedule_pk"]}/'))
    start = page.get_by_role('link', name='开始这次复测', exact=True)
    expect(start).to_be_visible(); start.focus(); start.press('Enter')
    expect(page.locator('#id_attempt_kind')).to_have_value('retest')
    expect(page.locator('#id_question_id')).to_have_value(fixture['question'])
    expect(page.get_by_role('heading', name='当前学习任务', exact=True)).to_be_visible()
    for field, value in [('source_kind','independent_answer'), ('independence','confirmed_independent'), ('prompt_status','none_confirmed'), ('actual_date_state','known'), ('legibility','readable')]:
        page.locator('#id_' + field).select_option(value)
    page.locator('#id_actual_date').fill('2026-10-07')
    page.locator('#id_answer_text').fill('8 厘米 · 合成连续流程')
    page.locator('#id_authorship_basis').fill('明确采用已确认的合成观察，仅用于隔离验收')
    page.locator('input[name=observation_values]').first.check()
    page.locator('#id_previous_attempt_id').select_option(fixture['attempt'])
    save = page.get_by_role('button', name='保存作答记录', exact=True)
    save.focus(); save.press('Enter')
    expect(page.get_by_text('复测作答已保存，待确认关联。', exact=False)).to_be_visible()
    capture_task('saved-pending-confirmation')
    bound = page.locator('#id_attempt_revision_id').input_value()
    assert bound and db(lambda: ScheduleRevision.objects.filter(schedule_id=plan['schedule_pk']).count()) == 1
    page.locator('#id_reason').fill('核对精确作答后确认，不推断掌握')
    complete = page.get_by_role('button', name='追加计划事件', exact=True)
    complete.focus(); complete.press('Enter')
    expect(page.get_by_role('heading', name='完成记录', exact=True)).to_be_visible()
    assert db(lambda: ScheduleRevision.objects.filter(schedule_id=plan['schedule_pk'], action='completed').get().completed_attempt_revision_id) == bound
    page.get_by_role('link', name='返回复习安排', exact=True).focus()
    page.get_by_role('link', name='返回复习安排', exact=True).press('Enter')
    expect(page.get_by_role('heading', name='复测计划', exact=True)).to_be_visible()
    capture_task('completed-return')
    page.goto(overview)
    expect(page.get_by_role('heading', name='近期作答记录', exact=True)).to_be_visible()
    assert not page.locator('section[aria-labelledby="learning-tasks-title"]').get_by_text('合成连续复测验收', exact=False).count()
    checks.append('follow-up-plan-keyboard-save-pending-exact-confirmation-return-and-action-refresh')

    # Native legacy form mounts the same formula helper, including its real API.
    page.goto(origin + '/knowledge/create/knowledge/?' + urlencode({'household_id': house.pk}))
    expect(page.get_by_role('button', name='分数', exact=True)).to_be_visible()
    page.get_by_role('button', name='分数', exact=True).press('Enter')
    insert = page.get_by_role('button', name='加入定义与排版', exact=True)
    expect(insert).to_be_enabled()
    insert.press('Enter')
    expect(page.locator('#id_definition')).to_have_value('1/2')
    expect(page.locator('#id_display_markup')).to_have_value('[[math:1/2]]')
    checks.append('follow-up-native-form-shared-formula-helper-keyboard-preview-insert')

    # Use a real authorized immutable snapshot; compare downloads with stored bytes.
    snapshot = db(lambda: ExportSnapshot.objects.filter(household=house).exclude(purpose='evidence_report').order_by('-created_at').first())
    assert snapshot is not None
    page.goto(origin + app_url(view='documents'))
    expect(page.get_by_role('tab', name='最近成果', exact=True)).to_have_attribute('aria-selected', 'true')
    request = page.request.get(origin + '/api/v1/documents/?' + urlencode({'household': house.pk, 'q': snapshot.title}))
    assert request.status == 200
    assert any(item['id'] == 'snapshot:' + str(snapshot.pk) for item in request.json()['items'])
    page.get_by_role('searchbox').fill(snapshot.title)
    page.get_by_role('button', name='查找成果', exact=True).press('Enter')
    row = page.locator('section[aria-label="最近成果"] > ul > li').filter(has=page.get_by_role('heading', name=snapshot.title, exact=True)).first
    expect(row).to_be_visible()
    with page.expect_download() as captured:
        word_link = row.get_by_role('link', name='下载 Word', exact=True)
        word_link.focus(); word_link.press('Enter')
    download = captured.value
    assert download.failure() is None
    target = output / 'follow-up-synthetic.docx'
    download.save_as(target)
    expected_sha = db(lambda: hashlib.sha256(printing.snapshot_file(actor, snapshot.pk, 'document.docx').read_bytes()).hexdigest())
    assert hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha
    trigger = row.get_by_role('link', name='预览 PDF', exact=True)
    trigger.focus(); trigger.press('Enter')
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_visible()
    expect(page.get_by_role('button', name='关闭预览', exact=True)).to_be_focused()
    page.keyboard.press('Shift+Tab')
    assert dialog.evaluate('(dialog) => dialog.contains(document.activeElement)')
    fallback = dialog.get_by_role('button', name='预览空白？查看逐页图片', exact=True)
    expect(fallback).to_be_visible()
    fallback.press('Enter')
    image = dialog.get_by_role('img')
    expect(image).to_be_visible()
    image.evaluate('(image) => image.decode()')
    capture_task('preview-image')
    page.screenshot(path=str(output / 'follow-up-authorized-pdf-image-fallback.png'), full_page=True)
    metadata = page.request.get(origin + f'/prints/snapshots/{snapshot.pk}/preview/')
    assert metadata.status == 200 and 'no-store' in metadata.headers['cache-control']
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(trigger).to_be_focused()
    checks.append('follow-up-recent-practice-word-download-sha-and-pdf-image-fallback-focus-return')
    if tool:
        checks.append('follow-up-native-200-percent-continuous-keyboard-plan-formula-preview-download-return')
        subprocess.run([tool, 'key', '--clearmodifiers', 'ctrl+0'], check=True)
    (output / 'acceptance-follow-up.local.json').write_text(json.dumps({'status':'passed', 'checks': [check for check in checks if check.startswith('follow-up-')], 'native_zoom': native_zoom, 'word_download_sha256': expected_sha, 'word_pc': 'not_tested', 'word_macos': 'not_tested', 'real_user_acceptance': 'not_tested'}, ensure_ascii=False, indent=2))
