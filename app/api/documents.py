"""Authorized read-only catalogue; formal output types retain their own services."""
from heapq import merge
from django.db.models import Q
from django.urls import reverse
from app.printing.models import ExportSnapshot
from app.operations.models import ExportRetirementRecord, ExportArchiveRecord
from app.solutions.models import SolutionOutput
from app.solutions.queries import output_row
from .views import api, household

PURPOSES = {'independent_practice': '无提示练习与复测', 'parent_answers': '家长答案与依据', 'evidence_report': '学习证据报告',
    'knowledge_summary': '五册 · 知识整理', 'classification_index': '五册 · 分类索引',
    'parent_analysis': '五册 · 家长解析', 'parent_solution': '家长解析'}


@api()
def catalogue(request):
    hid = household(request)
    if hid is None:
        return {'items': [], 'total': 0, 'page': 1, 'page_size': 20, 'has_next': False}
    query = request.GET.get('q', '').strip()[:200]
    category = request.GET.get('category', '')
    if category not in ('', 'practice', 'knowledge', 'solution', 'snapshot'):
        raise ValueError('Invalid document category')
    page = int(request.GET.get('page', '1'))
    page_size = int(request.GET.get('page_size', '20'))
    if page < 1 or not 1 <= page_size <= 100:
        raise ValueError('Invalid document page')
    outputs = SolutionOutput.objects.filter(revision__material__household_id=hid).select_related('revision__material')
    snapshots = ExportSnapshot.objects.filter(household_id=hid)
    if query:
        outputs = outputs.filter(Q(revision__material__title__icontains=query) | Q(result__documents__icontains=query))
        snapshots = snapshots.filter(title__icontains=query)
    if category in ('knowledge', 'solution'):
        outputs = outputs.filter(revision__mode=category)
        snapshots = snapshots.none()
    elif category in ('practice', 'snapshot'):
        outputs = outputs.none()
        if category == 'practice':
            snapshots = snapshots.filter(purpose__in=('independent_practice',))
    total = outputs.count() + snapshots.count()
    # Merge ordered projections before paging. Equal times use a typed identity only
    # as a deterministic catalogue tie, never as a real learning-event chronology.
    keyed_outputs = ((row.created_at, 'output:' + str(row.pk), 'output', row)
                     for row in outputs.order_by('-created_at', '-pk').iterator())
    keyed_snapshots = ((row.created_at, 'snapshot:' + str(row.pk), 'snapshot', row)
                       for row in snapshots.order_by('-created_at', '-pk').iterator())
    start = (page - 1) * page_size
    selected = []
    for index, entry in enumerate(merge(keyed_outputs, keyed_snapshots, key=lambda value: (value[0], value[2], value[3].pk), reverse=True)):
        if index >= start + page_size:
            break
        if index >= start:
            selected.append(entry)
    snapshot_ids = [row.pk for _, _, kind, row in selected if kind == 'snapshot']
    retired = set(ExportRetirementRecord.objects.filter(snapshot_id__in=snapshot_ids).values_list('snapshot_id', flat=True))
    archived = set(ExportArchiveRecord.objects.filter(snapshot_id__in=snapshot_ids).values_list('snapshot_id', flat=True))
    items = []
    for created, identity, kind, row in selected:
        if kind == 'output':
            value = output_row(row)
            blocked = row.state not in ('output_check', 'complete') or any(check.get('status') == 'fail' for check in value['checks'].values())
            items.append({'id': identity, 'category': row.revision.mode,
                'category_label': '知识讲解' if row.revision.mode == 'knowledge' else '家长解析',
                'title': row.revision.material.title, 'created_at': created, 'state_label': value['state_label'],
                'detail_url': f'/__app__/knowledge-explanations/{row.revision.material_id}/?panel=outputs' if row.revision.mode == 'knowledge' else f'/__app__/solutions/{row.revision.material_id}/?panel=outputs',
                'documents': [] if blocked else value['documents'], 'checks': value['checks'],
                'zip_url': None if blocked else value['zip_url'], 'message': value['message']})
        else:
            unavailable = row.pk in retired
            items.append({'id': identity, 'category': 'practice' if row.purpose in ('independent_practice',) else 'snapshot',
                'category_label': PURPOSES.get(row.purpose, '历史文档'), 'title': row.title, 'created_at': created,
                'state_label': '已退役，保留历史' if unavailable else '已归档' if row.pk in archived else '已生成，待核对',
                'detail_url': reverse('printing:snapshot', args=[row.pk]),
                'documents': [] if unavailable else [{'id': identity, 'title': row.title,
                    'pdf_url': reverse('printing:download', args=[row.pk, 'document.pdf']),
                    'docx_url': reverse('printing:download', args=[row.pk, 'document.docx'])}],
                'checks': {}, 'zip_url': None, 'message': '生成不代表内容、版式或 Word 客户端已验收。'})
    return {'items': items, 'total': total, 'page': page, 'page_size': page_size,
            'has_next': start + page_size < total, 'query': query, 'category': category}
