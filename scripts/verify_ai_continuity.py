"""Synthetic extension of verify_business's owned, loopback-only browser run.

Called by its runner after the AI-off and learning checks. All model responses
are patched in process before execute_run; no server worker or gateway is used.
"""
import json
import os
from unittest.mock import patch
from uuid import uuid4


def exercise(*, page, db, goto, screenshot, checks, actor, household_id, source_page):
    from django.test import override_settings
    from playwright.sync_api import expect
    from app.ai import services as ai
    from app.ai.models import ModelRun
    from app.persistence.models import EntityRecord, EvidenceRecord, RevisionRecord
    from app.web import services as materials
    from app.web.models import PageReadingRevision

    page_id = str(source_page.pk)
    learning_count = db(lambda: EntityRecord.objects.filter(household_id=household_id,
        kind__in=('attempt', 'assessment')).count())
    goto(f'/page/{page_id}/reading/', 'whole-page-reading')
    expect(page.locator('#page-reading-current')).to_contain_text('未阅读')
    page.locator('#id_reading').select_option('read')
    card = page.locator('.region-card')
    card.locator('.rotation-select').select_option('90')
    for kind, bbox in [('theory', (10, 20, 100, 200)), ('handwriting', (110, 20, 200, 200)),
            ('unknown', (210, 20, 300, 200))]:
        card.locator('.partition-kind').select_option(kind)
        for name, value in zip(('x0', 'y0', 'x1', 'y1'), bbox):
            card.locator(f'.coord-{name}').fill(str(value))
        card.locator('.add-coordinates').click()
    values = json.loads(page.locator('#id_sources').input_value())
    assert [v['kind'] for v in values] == ['theory', 'handwriting', 'unknown']
    page.locator('#id_pending_items').fill('合成图片右侧未知，未确认作者与独立性')
    page.locator('#id_basis').fill('合成整页人工查看，不推断掌握')
    page.get_by_role('button', name='保存整页状态与分区', exact=True).click()
    expect(page.locator('#page-reading-current')).to_contain_text('第 1 版')
    row = db(lambda: PageReadingRevision.objects.filter(page_id=page_id).first())
    assert row.partitions[0]['original_bbox'] == [20, source_page.image.payload['height'] - 100,
        200, source_page.image.payload['height'] - 10]
    assert row.original_sha256 == source_page.image.sha256
    assert len(json.loads(page.locator('#id_sources').input_value())) == 3
    page.locator('#id_reading').select_option('needs_retake')
    page.locator('#id_basis').fill('合成重拍计划，不覆盖旧分区')
    page.get_by_role('button', name='保存整页状态与分区', exact=True).click()
    expect(page.locator('#reading-version-1')).to_be_visible()
    expect(page.locator('#reading-version-2')).to_be_visible()
    assert db(lambda: PageReadingRevision.objects.filter(page_id=page_id).count()) == 2
    assert db(lambda: EntityRecord.objects.filter(household_id=household_id,
        kind__in=('attempt', 'assessment')).count()) == learning_count
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    screenshot('phone-page-reading.png')
    checks.extend(['page-reading-manual-rotated-partitions-and-hash',
        'page-reading-unknown-retake-append-without-learner-records'])

    def synthetic_runs():
        config_data = {'provider_label': '合成响应（未调用外部服务）', 'base_url': 'http://127.0.0.1:1/v1',
            'model': 'fabricated-model', 'connection_route': 'gateway', 'upstream_state': 'unknown',
            'known_upstream_providers': '', 'retention_state': 'unknown', 'retention_description': '',
            'confirm_external_processing': True, 'cloud_enabled': True, 'outbound_scope': 'selected_regions',
            'timeout_seconds': 2, 'max_output_tokens': 100, 'max_input_chars': 2000, 'max_calls': 4,
            'batch_budget': '10', 'input_price_per_million': '1', 'output_price_per_million': '1',
            'reserved_per_call': '0.1', 'non_billable_gateway': False}
        runs = []
        with override_settings(SWB_AI_ALLOW_TEST_HTTP=True, SWB_PRODUCTION=False,
                SWB_TEST_OWNER=actor.username):
            ai.create_model_config(actor, household_id, data=config_data)
            preview = materials.preview_file(actor, page_id, 0)
            source = {'page_id': page_id, 'rotation': 0, 'preview_sha256': preview.sha256,
                'display_bbox': [5, 10, 100, 150]}
            for number in (1, 2):
                question = materials.save_question(actor, source_page.material_id, printed_text='',
                    original_number=f'SYN-AI-{number}', sources=[source], request_key=uuid4().hex,
                    reason='合成空白题干，仅验证流程')
                rid = question['revision_id']
                region = str(EvidenceRecord.objects.get(source_id=rid, region__isnull=False).region_id)
                context = ai.selection_context(actor, household_id, 'question')
                run = ai.queue_run(actor, household_id, task_kind='question', source_revision_ids=[rid],
                    question_revision_ids=[rid], selected_region_revision_ids=[region],
                    selection_token=context['token'], request_key=uuid4().hex)
                response = json.dumps({'schema_version': 'study-workbench.ai.v1', 'task': 'question',
                    'source_revision_ids': [rid, region], 'tool_calls': [], 'proposal': {
                        'printed_text': f'合成识别第 {number} 题：3 + 4 = ?', 'missing_fields': [],
                        'classification_suggestion': None, 'analysis_suggestion': None}})
                ai.request_execution(actor, run.pk)
                with patch.dict(os.environ, {'SWB_MODEL_API_KEY': 'fabricated-browser-only'}), patch(
                        'app.ai.services.chat_completion', return_value=(response,
                            {'prompt_tokens': 30, 'completion_tokens': 20})) as mocked:
                    done = ai.execute_run(run.pk)
                assert mocked.call_count == 1 and done.status == 'awaiting_review'
                runs.append(str(run.pk))
            ai.create_model_config(actor, household_id, data={**config_data,
                'cloud_enabled': False, 'confirm_external_processing': False})
        return runs

    runs = db(synthetic_runs)
    for number, run_id in enumerate(runs, 1):
        if number == 1:
            goto(f'/ai/run/{run_id}/', 'ai-result-direct-review')
        else:
            page.get_by_role('link', name='下一条待核对', exact=True).click()
        expect(page).to_have_url(f'{page.url.split("/ai/")[0]}/ai/run/{run_id}/review/')
        expect(page.locator('main')).to_contain_text(f'合成识别第 {number} 题')
        source_section = page.get_by_role('heading', name='来源页面入口', exact=True).locator('..')
        expect(source_section.get_by_role('link')).to_have_count(1)
        expect(source_section.get_by_role('link')).to_have_attribute('href', f'/page/{page_id}/')
        assert db(lambda: ModelRun.objects.get(pk=run_id).output_revision_ids) == []
        expect(page.get_by_role('button', name='确认并保存', exact=True)).to_be_visible()
        page.locator('#id_checked').check()
        page.locator('#id_reason').fill('人工核对合成响应，未调用模型，不推断掌握')
        page.get_by_role('button', name='确认并保存', exact=True).click()
        expect(page.locator('main')).to_contain_text('已完成逐项核对')
        rid = db(lambda: ModelRun.objects.get(pk=run_id).output_revision_ids[0])
        assert db(lambda: RevisionRecord.objects.get(pk=rid).review_projection.state) == 'accepted'
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    assert db(lambda: EntityRecord.objects.filter(household_id=household_id,
        kind__in=('attempt', 'assessment')).count()) == learning_count
    assert not db(lambda: ai.latest_config(household_id).cloud_enabled)
    screenshot('phone-ai-confirmation.png')
    checks.extend(['ai-synthetic-response-direct-review-without-auto-save',
        'ai-explicit-single-confirmation-and-next-pending', 'ai-manual-confirmation-with-model-disabled'])
    page.set_viewport_size({'width': 1280, 'height': 900})
    expect(page.locator('main')).to_contain_text('已完成逐项核对')
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    screenshot('desktop-ai-confirmation.png')
    goto(f'/page/{page_id}/reading/', 'desktop-whole-page-history')
    expect(page.locator('#reading-version-1')).to_be_visible()
    expect(page.locator('#reading-version-2')).to_be_visible()
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth + 1')
    screenshot('desktop-page-reading.png')
    checks.append('desktop-ai-confirmation-and-page-history-layout')
    page.set_viewport_size({'width': 390, 'height': 844})
