import { sameOriginHref } from '../../components/shared'
import { CompanionWorkspace } from '../companion/workspace'
import type { CompanionConfig, CompanionWorkspaceProps } from '../companion/types'
import { SUBJECTS } from '../materials/subjects'
import { knowledgeApi } from './api'
import { KnowledgeEditor } from './editor'
import { isKnowledgeContent, KINDS, PROFILES, SECTIONS } from './model'
import type { KnowledgeContent, KnowledgeOutput, KnowledgeWorkspaceResponse } from './types'

const config: CompanionConfig<KnowledgeContent, KnowledgeOutput, KnowledgeWorkspaceResponse> = {
  mode: 'knowledge', title: '知识点讲解', defaultReason: '整理知识点讲解',
  introduction: '对照来源核对知识结论、适用条件和完整依据。讲解与真实作答分别记录，生成文档不会认定已经掌握。',
  generationHint: '填写完整结论、定义与条件、依赖及五部分讲解。原资料内容关联原图；补充知识明确标注来源类别。学校学科与讲解依据类别分别选择。',
  empty: { schema_version: 'swb.knowledge.v1', title: '', school_subject: 'unknown', learner_level: '', lectures: [], knowledge: [], outputs: { inventory: [], per_knowledge: [], per_lecture: [], combined: [] } },
  normalize: (content) => content, isContent: isKnowledgeContent,
  hasItems: (content) => content.knowledge.length > 0,
  canGenerate: (content) => Boolean(content.knowledge.length && Object.values(content.outputs).some((formats) => formats.length)
    && content.knowledge.every((item) => item.title.trim() && item.statement.trim() && item.definitions.trim()
      && (item.origin !== 'source' || item.sources.length)
      && ['thinking', 'construction', 'derivation', 'conclusion', 'pitfall'].every((section) => item.steps.some((step) => step.section === section && step.text.trim())))),
  checkNames: [['content', '内容与来源'], ['subject', '学科依据与完整讲解'], ['pdf_visual', 'PDF 页面版式'], ['word_pc', 'Windows Word 实机'], ['word_macos', 'macOS Word 实机']],
  api: knowledgeApi,
  editor: KnowledgeEditor,
  compare: ({ left, leftTitle, right, rightTitle, workspace }) => <div className='grid min-w-0 gap-4 xl:grid-cols-2'>
    <KnowledgeReview title={leftTitle} content={left} workspace={workspace} />
    <KnowledgeReview title={rightTitle} content={right} workspace={workspace} />
  </div>,
}

export function KnowledgeWorkspace(props: CompanionWorkspaceProps) {
  return <CompanionWorkspace {...props} config={config} />
}

function KnowledgeReview({ title, content, workspace }: { title: string; content: KnowledgeContent; workspace: KnowledgeWorkspaceResponse }) {
  const subject = SUBJECTS.find(([id]) => id === content.school_subject)?.[1] || '未分类'
  const outputLabels = { inventory: '知识点目录', per_knowledge: '逐知识点', per_lecture: '按讲次', combined: '合集' }
  return <section className='min-w-0 space-y-3 rounded-md border p-3'>
    <h3 className='font-semibold'>{title}</h3>
    <p className='whitespace-pre-wrap break-words text-sm'>{content.title || '未填标题'} · {subject} · {content.learner_level || '层级未填'}</p>
    <p className='text-sm'>输出：{Object.entries(content.outputs).flatMap(([key, formats]) => formats.map((format) => `${outputLabels[key as keyof typeof outputLabels]} ${format.toUpperCase()}`)).join('、') || '未选'}</p>
    {content.lectures.map((lecture) => <p key={lecture.id} className='text-sm'>{lecture.title} · {PROFILES[lecture.rule_profile]}</p>)}
    {content.knowledge.map((item) => <article key={item.id} className='min-w-0 space-y-2 border-t pt-3 text-sm'>
      <h4 className='font-medium'>{item.order}. {item.title || '未填知识标题'} · {KINDS[item.kind]}</h4>
      <p>来源类别：{item.origin === 'source' ? '本资料' : item.origin === 'foundation' ? '基础知识' : '作者补充'}；关联条目：{workspace.nodes.find((node) => node.revision_id === item.knowledge_revision_id)?.label || '尚未关联'}</p>
      <p>依赖：{item.dependencies.map((id) => content.knowledge.find((entry) => entry.id === id)?.title || '未找到关联内容').join('、') || '无'}</p>
      {item.sources.map((source) => {
        const page = workspace.pages.find((row) => row.id === source.page_id)
        const href = sameOriginHref(page?.preview_url)
        return <div key={source.page_id} className='space-y-1'><p>{page?.label || '原图不可用'} · 印刷页码 {source.printed_page || '未知'} · {source.region ? `选区 ${source.region.join(' / ')}` : '整页'}</p>{href ? <a href={href} className='underline'><img src={href} alt='知识来源原图' className='max-h-64 w-full object-contain' /></a> : null}</div>
      })}
      {([['原文', item.original], ['完整结论', item.statement], ['定义／符号', item.definitions], ['条件', item.conditions.join('\n')]] as const).map(([label, value]) => <p key={label} className='whitespace-pre-wrap break-words'><strong>{label}：</strong>{value || '未填'}</p>)}
      {item.steps.map((step) => <div key={step.id} className='space-y-1 rounded-md border p-2'>
        <p className='font-medium'>{SECTIONS[step.section]}{step.new_page ? ' · 从新页开始' : ''}</p><p className='whitespace-pre-wrap break-words'>{step.text || '未填'}</p>
        {step.formula ? <p className='whitespace-pre-wrap break-words font-mono text-xs'>{step.formula}</p> : null}
        {step.figure ? <figure>{(() => { const asset = workspace.assets.find((row) => row.id === step.figure?.asset_id); const href = sameOriginHref(asset?.url); return href ? <img className='max-h-72 w-full object-contain' src={href} alt={asset?.label || step.figure.caption} /> : <p>图示当前不可用</p> })()}<figcaption>{step.figure.caption} · {step.figure.width_mm} mm · {step.figure.role === 'question' ? '原文图示' : step.figure.role === 'method' ? '讲解图示' : '结论图示'}</figcaption></figure> : null}
      </div>)}
      {item.corrections.map((correction, index) => <p key={index} className='whitespace-pre-wrap break-words'>订正：{correction.original} → {correction.replacement}；依据：{correction.basis}</p>)}
      <p className='whitespace-pre-wrap break-words'>未确定：{item.unknowns.join('\n') || '无'}</p>
    </article>)}
  </section>
}
