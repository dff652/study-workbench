import { useEffect, useState } from 'react'
import { Button } from '../../components/ui/button'
import { Disclosure } from '../../components/disclosure'
import { WorkspacePanel, WorkspaceTabs } from '../../components/workspace-tabs'
import { sameOriginHref } from '../../components/shared'
import { ImageBoxPicker } from '../content/image-box-picker'
import { SubjectSelect } from '../materials/subjects'
import { newSolutionId, newSolutionStep } from '../solutions/model'
import { AssetUploader, CorrectionEditor, StepFormulaPreview, StringListEditor } from '../solutions/editor'
import { KINDS, PROFILE_KINDS, PROFILES, SECTIONS, newKnowledgeItem } from './model'
import type { KnowledgeContent, KnowledgeItem, KnowledgeWorkspaceResponse, RuleProfile, Section } from './types'

const field = 'mt-1 w-full rounded-md border bg-background px-3 py-2 text-sm font-normal'

export function KnowledgeEditor({ focusItem, content, workspace, materialId, csrfToken, writable, onChange, onAssetsChanged, onBusyChange, onUnauthorized }: {
  focusItem?: { id: string }; content: KnowledgeContent; workspace: KnowledgeWorkspaceResponse; materialId: string; csrfToken: string; writable: boolean
  onChange: (content: KnowledgeContent) => void; onAssetsChanged: (assets: KnowledgeWorkspaceResponse['assets']) => void
  onBusyChange: (busy: boolean) => void; onUnauthorized: () => void
}) {
  const [activeId, setActiveId] = useState(content.knowledge[0]?.id || '')
  useEffect(() => { if (focusItem && content.knowledge.some((item) => item.id === focusItem.id)) setActiveId(focusItem.id) }, [focusItem])
  const [assetBusy, setAssetBusy] = useState(false)
  useEffect(() => { if (!content.knowledge.some((item) => item.id === activeId)) setActiveId(content.knowledge[0]?.id || '') }, [activeId, content.knowledge])
  const active = content.knowledge.find((item) => item.id === activeId)
  const disabled = !writable || assetBusy
  const busy = (value: boolean) => { setAssetBusy(value); onBusyChange(value) }
  const change = (patch: Partial<KnowledgeItem>) => { if (active) onChange({ ...content, knowledge: content.knowledge.map((item) => item.id === active.id ? { ...item, ...patch } : item) }) }
  return <div className='space-y-4'>
    <Disclosure title='讲解文档设置' description='学校学科、学习层级、讲次及输出格式；讲解依据类别由作者另选。'>
      <div className='grid gap-3 md:grid-cols-3'>
        <label className='text-sm font-medium'>文档标题<input className={field} maxLength={160} value={content.title} disabled={disabled} onChange={(event) => onChange({ ...content, title: event.target.value })} /></label>
        <SubjectSelect value={content.school_subject} disabled={disabled} onChange={(school_subject) => onChange({ ...content, school_subject })} />
        <label className='text-sm font-medium'>学习层级<input className={field} maxLength={160} value={content.learner_level} disabled={disabled} placeholder='例如：初中，先核对基础概念' onChange={(event) => onChange({ ...content, learner_level: event.target.value })} /></label>
      </div>
      <div className='mt-4 space-y-3'>
        <div className='flex items-center justify-between gap-2'><h3 className='text-sm font-semibold'>讲次与讲解依据</h3><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ ...content, lectures: [...content.lectures, { id: newSolutionId('lecture'), title: `第 ${content.lectures.length + 1} 讲`, rule_profile: 'mathematics' }] })}>添加讲次</Button></div>
        {content.lectures.map((lecture) => <div key={lecture.id} className='grid items-end gap-2 md:grid-cols-[1fr_1fr_auto]'>
          <label className='text-sm'>讲次名称<input className={field} maxLength={160} value={lecture.title} disabled={disabled} onChange={(event) => onChange({ ...content, lectures: content.lectures.map((item) => item.id === lecture.id ? { ...item, title: event.target.value } : item) })} /></label>
          <label className='text-sm'>讲解依据类别<select className={field} value={lecture.rule_profile} disabled={disabled} onChange={(event) => onChange({ ...content, lectures: content.lectures.map((item) => item.id === lecture.id ? { ...item, rule_profile: event.target.value as RuleProfile } : item) })}>{Object.entries(PROFILES).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label>
          <Button type='button' size='sm' variant='outline' disabled={disabled || content.lectures.length < 2 || content.knowledge.some((item) => item.lecture_id === lecture.id)} onClick={() => onChange({ ...content, lectures: content.lectures.filter((item) => item.id !== lecture.id) })}>删除讲次</Button>
        </div>)}
        <p className='text-xs text-muted-foreground'>改变依据类别后请核对每条知识性质与证明范围；已有内容不会自动改写。</p>
      </div>
      <div className='mt-4 grid gap-2 md:grid-cols-4'>{([['inventory', '知识清单'], ['per_knowledge', '逐知识点'], ['per_lecture', '按讲次'], ['combined', '完整合集']] as const).map(([organization, label]) => <fieldset key={organization} className='rounded-md border p-3'><legend className='px-1 text-sm font-medium'>{label}</legend>{(['pdf', 'docx'] as const).map((format) => <label key={format} className='mr-3 inline-flex items-center gap-2 text-sm'><input type='checkbox' disabled={disabled} checked={content.outputs[organization].includes(format)} onChange={(event) => onChange({ ...content, outputs: { ...content.outputs, [organization]: event.target.checked ? [...content.outputs[organization], format] : content.outputs[organization].filter((item) => item !== format) } })} />{format === 'docx' ? 'Word' : 'PDF'}</label>)}</fieldset>)}</div>
    </Disclosure>
    <div className='grid min-w-0 gap-4 lg:grid-cols-[minmax(14rem,0.3fr)_minmax(0,1fr)]'>
      <aside className='min-w-0 space-y-3 border-b pb-3 lg:border-r lg:border-b-0 lg:pr-4'>
        <div className='flex items-center justify-between gap-2'><h3 className='font-semibold'>知识条目 · {content.knowledge.length}</h3><Button type='button' size='sm' variant='outline' disabled={disabled || !content.lectures.length} onClick={() => { const lecture = content.lectures[0]; if (!lecture) return; const order = Math.max(0, ...content.knowledge.filter((item) => item.lecture_id === lecture.id).map((item) => item.order)) + 1; const item = newKnowledgeItem(lecture.id, order); onChange({ ...content, knowledge: [...content.knowledge, item] }); setActiveId(item.id) }}>添加知识点</Button></div>
        <ol className='space-y-1'>{content.knowledge.map((item) => <li key={item.id}><button type='button' aria-pressed={activeId === item.id} disabled={assetBusy} className={`w-full rounded-md border p-2 text-left text-sm ${activeId === item.id ? 'border-primary bg-primary/5' : ''}`} onClick={() => setActiveId(item.id)}>{item.order}. {item.title || '待命名知识'}<span className='mt-1 block text-xs text-muted-foreground'>{content.lectures.find((lecture) => lecture.id === item.lecture_id)?.title}</span></button></li>)}</ol>
        {!content.knowledge.length ? <p className='text-sm text-muted-foreground'>先添加知识，按原页填写结论，再完整说明依据。</p> : null}
      </aside>
      {active ? <ItemEditor key={active.id} item={active} content={content} workspace={workspace} materialId={materialId} csrfToken={csrfToken} disabled={disabled} onChange={change} onRemove={() => { if (content.knowledge.some((item) => item.dependencies.includes(active.id))) return; onChange({ ...content, knowledge: content.knowledge.filter((item) => item.id !== active.id) }) }} removable={!content.knowledge.some((item) => item.dependencies.includes(active.id))} onAssetsChanged={onAssetsChanged} onBusyChange={busy} onUnauthorized={onUnauthorized} /> : <div className='text-sm text-muted-foreground'>选择或添加一条知识以开始整理。</div>}
    </div>
  </div>
}

function ItemEditor({ item, content, workspace, materialId, csrfToken, disabled, onChange, onRemove, removable, onAssetsChanged, onBusyChange, onUnauthorized }: {
  item: KnowledgeItem; content: KnowledgeContent; workspace: KnowledgeWorkspaceResponse; materialId: string; csrfToken: string; disabled: boolean
  onChange: (patch: Partial<KnowledgeItem>) => void; onRemove: () => void; removable: boolean
  onAssetsChanged: (assets: KnowledgeWorkspaceResponse['assets']) => void; onBusyChange: (busy: boolean) => void; onUnauthorized: () => void
}) {
  const [tab, setTab] = useState('source')
  const [pageId, setPageId] = useState(item.sources[0]?.page_id || workspace.pages[0]?.id || '')
  const lecture = content.lectures.find((entry) => entry.id === item.lecture_id)
  const profile = lecture?.rule_profile || 'mathematics'
  const page = workspace.pages.find((entry) => entry.id === pageId)
  const source = item.sources.find((entry) => entry.page_id === pageId)
  const addSource = (region: [number, number, number, number] | null) => {
    if (!page || disabled) return
    onChange({ sources: [...item.sources.filter((ref) => ref.page_id !== page.id), { page_id: page.id, region, printed_page: source?.printed_page || null }] })
  }
  return <div className='min-w-0 space-y-3'>
    <header className='flex flex-wrap items-center justify-between gap-2'><h3 className='font-semibold'>{item.title || '整理知识点'}</h3><Button type='button' size='sm' variant='outline' disabled={disabled || !removable} onClick={onRemove}>删除此知识</Button></header>
    {!removable ? <p className='text-xs text-muted-foreground'>其他知识仍依赖本条，移除依赖后才可删除。</p> : null}
    <WorkspaceTabs id={`knowledge-item-${item.id}`} label='知识编写内容' tabs={[{ value: 'source', label: '结论与来源' }, { value: 'explanation', label: '证明与讲解' }, { value: 'notes', label: '订正与图示' }]} value={tab} onChange={setTab} />
    <WorkspacePanel id={`knowledge-item-${item.id}`} value='source' active={tab}>
      <div className='grid gap-3 md:grid-cols-2'>
        <label className='text-sm font-medium'>知识名称<input className={field} disabled={disabled} maxLength={160} value={item.title} onChange={(event) => onChange({ title: event.target.value })} /></label>
        <label className='text-sm font-medium'>所属讲次<select className={field} disabled={disabled} value={item.lecture_id} onChange={(event) => { const id = event.target.value; const order = Math.max(0, ...content.knowledge.filter((entry) => entry.id !== item.id && entry.lecture_id === id).map((entry) => entry.order)) + 1; onChange({ lecture_id: id, order }) }}>{content.lectures.map((entry) => <option key={entry.id} value={entry.id}>{entry.title}</option>)}</select></label>
        <label className='text-sm font-medium'>知识性质<select className={field} disabled={disabled} value={item.kind} onChange={(event) => onChange({ kind: event.target.value as KnowledgeItem['kind'] })}>{Object.entries(KINDS).map(([id, name]) => <option key={id} value={id} disabled={!PROFILE_KINDS[profile].includes(id as KnowledgeItem['kind'])}>{name}</option>)}</select></label>
        <label className='text-sm font-medium'>知识归属<select className={field} disabled={disabled} value={item.origin} onChange={(event) => onChange({ origin: event.target.value as KnowledgeItem['origin'] })}><option value='source'>原页知识</option><option value='foundation'>基础知识</option><option value='supplement'>补充知识</option></select></label>
      </div>
      {(['original', 'statement', 'definitions'] as const).map((name) => <label key={name} className='block text-sm font-medium'>{({ original: '原页结论', statement: '完整结论', definitions: '定义、字母与变量' })[name]}<textarea className={`${field} min-h-20`} maxLength={2000} disabled={disabled} value={item[name]} onChange={(event) => onChange({ [name]: event.target.value })} /></label>)}
      <StringListEditor title='适用条件' values={item.conditions} disabled={disabled} onChange={(conditions) => onChange({ conditions })} />
      <label className='block text-sm font-medium'>关联已有知识版本（可选）<select className={field} disabled={disabled} value={item.knowledge_revision_id || ''} onChange={(event) => onChange({ knowledge_revision_id: event.target.value || null })}><option value=''>独立讲解，暂不关联</option>{workspace.nodes.filter((node) => node.kind === 'knowledge').map((node) => <option key={node.revision_id} value={node.revision_id} disabled={node.selectable === false}>{node.label}</option>)}</select></label>
      <fieldset className='space-y-2 rounded-md border p-3'><legend className='px-1 text-sm font-medium'>本册讲解依赖</legend>{content.knowledge.filter((entry) => entry.id !== item.id).map((entry) => <label key={entry.id} className='mr-4 inline-flex items-center gap-2 text-sm'><input type='checkbox' disabled={disabled} checked={item.dependencies.includes(entry.id)} onChange={(event) => onChange({ dependencies: event.target.checked ? [...item.dependencies, entry.id] : item.dependencies.filter((id) => id !== entry.id) })} />{entry.title || '待命名知识'}</label>)}<p className='text-xs text-muted-foreground'>声明前置知识；循环依赖须人工调整，不能用例子替代一般证明。</p></fieldset>
      <label className='block text-sm font-medium'>对照原图<select className={field} value={pageId} onChange={(event) => setPageId(event.target.value)}>{workspace.pages.map((entry) => <option key={entry.id} value={entry.id}>{entry.label}</option>)}</select></label>
      {page ? <ImageBoxPicker page={{ id: page.id, width: page.width, height: page.height, position: page.position ?? workspace.pages.findIndex((entry) => entry.id === page.id) + 1, sha256: page.sha256 || '', page_url: page.detail_url, preview_url: page.preview_url }} boxes={source?.region ? [{ bbox: source.region, label: '知识来源' }] : []} disabled={disabled} onAdd={addSource} /> : <p className='text-sm text-muted-foreground'>先在资料整理中上传原图；基础或补充知识没有原页时明确标注。</p>}
      {page ? <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => addSource(null)}>记录整页来源（区域未知）</Button> : null}
      <ul className='space-y-2'>{item.sources.map((ref) => <li key={ref.page_id} className='space-y-2 rounded-md border p-3 text-sm'><div className='flex flex-wrap items-center justify-between gap-2'><span>{workspace.pages.find((entry) => entry.id === ref.page_id)?.label || '来源页'} · {ref.region ? `原图区域 ${ref.region.join(', ')} px` : '整页，区域未知'}</span><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ sources: item.sources.filter((entry) => entry.page_id !== ref.page_id) })}>移除此来源</Button></div><label className='block text-xs font-medium'>印刷页码（未知可留空）<input className={field} maxLength={160} disabled={disabled} value={ref.printed_page || ''} onChange={(event) => onChange({ sources: item.sources.map((entry) => entry.page_id === ref.page_id ? { ...entry, printed_page: event.target.value || null } : entry) })} /></label></li>)}</ul>
    </WorkspacePanel>
    <WorkspacePanel id={`knowledge-item-${item.id}`} value='explanation' active={tab}>
      <p className='text-sm text-muted-foreground'>五部分均需实质文字。数学给出一般证明，科学标明观察范围，语言与人文按具体文本和证据解释。</p>
      {item.steps.map((step, index) => <section key={step.id} className='space-y-3 rounded-md border p-3'>
        <div className='flex flex-wrap items-center gap-2'><label className='min-w-40 flex-1 text-sm font-medium'>第 {index + 1} 步<select className={field} disabled={disabled} value={step.section} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id ? { ...entry, section: event.target.value as Section } : entry) })}>{Object.entries(SECTIONS).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><Button type='button' size='sm' variant='outline' disabled={disabled || index === 0} onClick={() => { const steps = [...item.steps]; [steps[index - 1], steps[index]] = [steps[index]!, steps[index - 1]!]; onChange({ steps }) }}>上移</Button><Button type='button' size='sm' variant='outline' disabled={disabled || index === item.steps.length - 1} onClick={() => { const steps = [...item.steps]; [steps[index], steps[index + 1]] = [steps[index + 1]!, steps[index]!]; onChange({ steps }) }}>下移</Button><Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ steps: item.steps.filter((entry) => entry.id !== step.id) })}>删除步骤</Button></div>
        <label className='block text-sm font-medium'>{SECTIONS[step.section]}<textarea className={`${field} min-h-24`} maxLength={2000} disabled={disabled} value={step.text} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id ? { ...entry, text: event.target.value } : entry) })} /></label>
        <Disclosure title={`第 ${index + 1} 步公式、图示与分页`}>
          <StepFormulaPreview stepId={step.id} stepNumber={index + 1} value={step.formula || ''} csrfToken={csrfToken} disabled={disabled} onUnauthorized={onUnauthorized} onChange={(formula) => onChange({ steps: item.steps.map((entry) => entry.id === step.id ? { ...entry, formula: formula || null } : entry) })} />
          <label className='mt-3 block text-sm font-medium'>附图<select className={field} value={step.figure?.asset_id || ''} disabled={disabled} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id ? { ...entry, figure: event.target.value ? { asset_id: event.target.value, role: 'method', caption: '', width_mm: 90 } : null } : entry) })}><option value=''>不附图</option>{workspace.assets.filter((asset) => !asset.source || item.sources.some((ref) => ref.page_id === asset.source?.page_id && JSON.stringify(ref.region) === JSON.stringify(asset.source.region))).map((asset) => <option key={asset.id} value={asset.id}>{asset.label}</option>)}</select></label>
          {step.figure ? <div className='mt-3 grid gap-2 md:grid-cols-2'><label className='text-sm'>图注<input className={field} maxLength={2000} value={step.figure.caption} disabled={disabled} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id && entry.figure ? { ...entry, figure: { ...entry.figure, caption: event.target.value } } : entry) })} /></label><label className='text-sm'>图宽（毫米）<input className={field} type='number' min={10} max={172} value={step.figure.width_mm} disabled={disabled} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id && entry.figure ? { ...entry, figure: { ...entry.figure, width_mm: Number(event.target.value) } } : entry) })} /></label></div> : null}
          <label className='mt-3 flex items-center gap-2 text-sm'><input type='checkbox' disabled={disabled} checked={step.new_page} onChange={(event) => onChange({ steps: item.steps.map((entry) => entry.id === step.id ? { ...entry, new_page: event.target.checked } : entry) })} />本步从新页开始</label>
        </Disclosure>
      </section>)}
      <Button type='button' size='sm' variant='outline' disabled={disabled} onClick={() => onChange({ steps: [...item.steps, { ...newSolutionStep(), section: 'derivation' }] })}>添加讲解步骤</Button>
    </WorkspacePanel>
    <WorkspacePanel id={`knowledge-item-${item.id}`} value='notes' active={tab}>
      <StringListEditor title='待核项与依据缺口' values={item.unknowns} disabled={disabled} onChange={(unknowns) => onChange({ unknowns })} />
      <CorrectionEditor corrections={item.corrections} disabled={disabled} onChange={(corrections) => onChange({ corrections })} />
      <AssetUploader question={{ id: item.id, sources: item.sources.map(({ page_id, region }) => ({ page_id, region })) }} sourceLabel='当前知识' pages={workspace.pages} assets={workspace.assets} materialId={materialId} csrfToken={csrfToken} disabled={disabled} onBusyChange={onBusyChange} onAssetsChanged={onAssetsChanged} onUnauthorized={onUnauthorized} />
      <div className='grid gap-3 sm:grid-cols-2 lg:grid-cols-3'>{workspace.assets.map((asset) => <figure key={asset.id} className='space-y-1 rounded-md border p-2'><img src={sameOriginHref(asset.url) || undefined} alt={asset.label} className='max-h-32 w-full object-contain' loading='lazy' /><figcaption className='break-words text-xs'>{asset.label} · {asset.basis}</figcaption></figure>)}</div>
    </WorkspacePanel>
  </div>
}
