import type { WorkflowJob } from '../../types'

const STATES: Record<WorkflowJob['state'], string> = {
  needs_review: '待确认',
  ready: '待排队',
  queued: '排队中',
  running: '处理中',
  output_check: '待检查输出',
  complete: '已完成',
  failed: '处理失败',
  cancelled: '已取消',
}

const ACTIONS: Record<string, string> = {
  created: '创建任务',
  confirm: '确认整包内容',
  queue: '加入处理队列',
  started: '开始处理',
  rendered: '生成五册检查版',
  check_output: '确认输出检查',
  cancel: '取消任务',
  resume: '恢复处理',
  failed: '处理失败',
  interrupted: '任务中断',
}

export function workflowStateLabel(state: string) {
  return STATES[state as WorkflowJob['state']] || '状态更新'
}

export function workflowActionLabel(action: string) {
  return ACTIONS[action] || '任务记录'
}

export function localDateTime(value: string) {
  const parsed = new Date(value)
  if (Number.isNaN(parsed.valueOf())) return '时间未提供'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit',
  }).format(parsed)
}
