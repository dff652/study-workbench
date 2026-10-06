import { BookOpen, CalendarDays, PencilLine } from 'lucide-react'
import { Button } from './ui/button'
import { HelpTip } from './help-tip'

export function LearningStart({ learnerName, canWrite, parentMode = false, onPractice, onExplanation, onReview, onMaterials, onRecord, onHistory }: {
  learnerName: string; canWrite: boolean; parentMode?: boolean
  onPractice: () => void; onExplanation: () => void; onReview: () => void
  onMaterials: () => void; onRecord: () => void; onHistory: () => void
}) {
  return <section aria-labelledby='learning-start-title' className='border-b pb-4'>
    <div className='flex items-center gap-2'>
      <h2 id='learning-start-title' className='text-base font-semibold'>今天从哪里开始？</h2>
      <HelpTip label='学习顺序帮助'>先选题自己做，再看讲解、核对过程。需要帮助时，可以和家长一起整理照片、记录作答或安排复习。</HelpTip>
    </div>
    <div className='mt-3 flex flex-wrap gap-2'>
      <Button type='button' onClick={onPractice}><PencilLine className='size-4' aria-hidden='true' />选题练习</Button>
      <Button type='button' variant='outline' onClick={onExplanation}><BookOpen className='size-4' aria-hidden='true' />查看讲解</Button>
      <Button type='button' variant='outline' onClick={onReview}><CalendarDays className='size-4' aria-hidden='true' />复习安排</Button>
    </div>
    <details open={parentMode} className='mt-3'><summary className='cursor-pointer text-sm font-medium'>家长整理与记录</summary><div className='mt-2 flex flex-wrap gap-2' aria-label='资料与作答操作'>
      {canWrite ? <Button type='button' variant='outline' onClick={onMaterials}>整理学习资料</Button> : null}
      {canWrite && learnerName ? <Button type='button' variant='outline' onClick={onRecord}>记录一次作答</Button> : null}
      <Button type='button' variant='ghost' onClick={onHistory}>查看学习记录</Button>
    </div></details>
  </section>
}
