"""Anonymous author-written examples; science and humanities records are fictional."""
from copy import deepcopy


SECTIONS = ('thinking', 'construction', 'derivation', 'conclusion', 'pitfall')
SAMPLES = {
    'mathematics': {
        'subject': 'mathematics', 'kind': 'theorem', 'title': '两个偶数之和',
        'statement': '任意两个偶整数相加，结果仍是偶整数。',
        'definitions': '偶整数是能够写成二乘整数的整数。设两个偶整数分别为 2m 与 2n，其中 m 和 n 都是整数。',
        'conditions': ['参与相加的两个数都是整数。', '两个数都能被二整除。'],
        'explanation': [
            '先把偶数的定义变成可以计算的表达式，再检查和是否仍满足同一定义。',
            '设两个偶整数分别为 2m 与 2n。引入整数 m 和 n，是为了把整除条件改写成乘法。',
            '两数相加得 2m+2n=2(m+n)。整数对加法封闭，所以 m+n 仍是整数；这个和是二乘整数。',
            '任意两个偶整数相加，结果仍是偶整数。上述定义和整数对加法封闭共同保证了该结论。',
            '本结论限于两个偶整数。不能据此断言任意两个整数的和为偶数，也不能省略整数条件。',
        ],
    },
    'science': {
        'subject': 'physics', 'kind': 'empirical_rule', 'title': '匿名电路观察',
        'statement': '这份虚构观察记录中，开关闭合时灯泡亮，断开时灯泡不亮。',
        'definitions': '这是为验证软件流程编写的虚构观察。装置由同一电池、灯泡、导线和开关组成，亮或不亮按记录判定。',
        'conditions': ['仅比较本记录中的同一装置。', '记录假设电池、灯泡和连接正常，其他因素保持不变。'],
        'explanation': [
            '先区分观察记录与一般规律，确定这组材料只提供同一装置的两种开关状态。',
            '把电池、灯泡和连接固定，比较闭合与断开；这样可以明确记录中改变的因素。',
            '匿名记录第一行写闭合和亮，第二行写断开和不亮。闭合使回路连通，断开使回路中断；这里依据的是虚构记录和回路条件。',
            '这份虚构观察记录中，开关闭合时灯泡亮，断开时灯泡不亮。它描述指定记录，不能替代真实实验。',
            '不能把该示例当成真实观察，也不能推广到电池耗尽、灯泡损坏或连接异常的装置。',
        ],
    },
    'language': {
        'subject': 'english', 'kind': 'interpretation', 'title': '现在进行时的语境',
        'statement': '本句 is reading 表示 Lina 在说话时正在阅读。',
        'definitions': '匿名句子为 Look! Lina is reading now.；is 是与单数主语对应的 be 动词，reading 是 read 的现在分词。',
        'conditions': ['解释限定于给定句子和当前语境。', 'Look 和 now 提供说话时正在发生的语境。'],
        'explanation': [
            '先看句中的动作和时间提示，再检查 be 动词与现在分词组成的结构。',
            '把 Lina、is reading 和 now 分别作为主语、谓语和时间提示，说明这样划分的依据。',
            '句中 is 与 reading 组成 be 加现在分词，now 与 Look 指向当前动作。结合这些证据，动作发生在说话时。',
            '本句 is reading 表示 Lina 在说话时正在阅读。这个解释同时使用句法结构和给定语境。',
            '不能只凭一个以 ing 结尾的词判断时态，也不能忽略 be 动词或把其他语境一律解释为当前动作。',
        ],
    },
    'humanities': {
        'subject': 'history', 'kind': 'interpretation', 'title': '匿名材料的先后顺序',
        'statement': '按这两份虚构记录标注的日期，活动 A 早于活动 B。',
        'definitions': '虚构社团记录甲注明活动 A 于 2010 年 3 月，记录乙注明活动 B 于 2012 年 4 月；这里仅判断记录所述日期。',
        'conditions': ['只比较两份材料明确标注的日期。', '示例假定日期记载准确，不推断材料没有说明的事实。'],
        'explanation': [
            '先确认材料写了什么和没有写什么，把时间先后问题与原因解释分开。',
            '从两份材料提取年份和月份并按年月排列；这样比较的是可定位的日期证据。',
            '记录甲为 2010 年 3 月，记录乙为 2012 年 4 月。2010 年早于 2012 年，因此记录中的活动 A 日期在活动 B 之前。',
            '按这两份虚构记录标注的日期，活动 A 早于活动 B。这只是对匿名材料日期的比较。',
            '先发生不证明因果关系。两份虚构材料不能冒充真实历史证据，日期有误时应重新核对而保留未知。',
        ],
    },
}


def knowledge_content(page_id, profiles=('mathematics',)):
    content = {'schema_version': 'swb.knowledge.v1', 'title': '匿名知识讲解',
        'school_subject': SAMPLES[profiles[0]]['subject'] if len(profiles) == 1 else 'other',
        'learner_level': '初中示例；只验证内容与产品流程', 'lectures': [], 'knowledge': [],
        'outputs': {name: ['pdf', 'docx'] for name in ('inventory', 'per_knowledge', 'per_lecture', 'combined')}}
    for position, profile in enumerate(profiles, 1):
        sample = deepcopy(SAMPLES[profile]); identifier = 'knowledge-' + profile
        lecture_id = 'lecture-' + profile
        content['lectures'].append({'id': lecture_id, 'title': sample['title'], 'rule_profile': profile})
        content['knowledge'].append({'id': identifier, 'knowledge_revision_id': None,
            'lecture_id': lecture_id, 'order': 1, 'title': sample['title'], 'kind': sample['kind'], 'origin': 'source',
            'sources': [{'page_id': page_id, 'region': None, 'printed_page': str(position)}],
            'original': sample['statement'], 'statement': sample['statement'], 'definitions': sample['definitions'],
            'conditions': sample['conditions'], 'dependencies': [],
            'steps': [{'id': identifier + '-' + section, 'section': section, 'text': text,
                'formula': None, 'figure': None, 'new_page': False}
                for section, text in zip(SECTIONS, sample['explanation'], strict=True)],
            'corrections': [], 'unknowns': ['虚构匿名材料，仅用于软件验收。']})
    return content
