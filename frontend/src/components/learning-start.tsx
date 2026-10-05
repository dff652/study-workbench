import { BookOpen, CalendarDays, PencilLine } from 'lucide-react'
import { Button } from './ui/button'
import { HelpTip } from './help-tip'

export function LearningStart({ learnerName, canWrite, onPractice, onExplanation, onReview, onMaterials, onRecord, onHistory }: {
  learnerName: string; canWrite: boolean
  onPractice: () => void; onExplanation: () => void; onReview: () => void
  onMaterials: () => void; onRecord: () => void; onHistory: () => void
}) {
  return <section aria-labelledby='learning-start-title' className='rounded-xl border bg-background p-5 shadow-sm sm:p-6'>
    <div className='flex items-center gap-2'>
      <h2 id='learning-start-title' className='text-lg font-semibold'>{learnerName ? `${learnerName}，今天从哪里开始？` : '今天从哪里开始？'}</h2>
      <HelpTip label='学习顺序帮助'>先选题自己做，再看讲解、核对过程。需要帮助时，可以和家长一起整理照片、记录作答或安排复习。</HelpTip>
    </div>
    <p className='mt-2 text-sm leading-6 text-muted-foreground'>一次做好一小步。先自己试试，遇到不清楚的地方可以保留，稍后再核对。</p>
    <div className='mt-5 grid gap-3 sm:grid-cols-3'>
      <Button type='button' className='h-auto min-h-12 gap-2 py-3' onClick={onPractice}><PencilLine className='size-4' aria-hidden='true' />选题练习</Button>
      <Button type='button' variant='outline' className='h-auto min-h-12 gap-2 py-3' onClick={onExplanation}><BookOpen className='size-4' aria-hidden='true' />查看讲解</Button>
      <Button type='button' variant='outline' className='h-auto min-h-12 gap-2 py-3' onClick={onReview}><CalendarDays className='size-4' aria-hidden='true' />复习安排</Button>
    </div>
    <details className='mt-5 border-t pt-4'>
      <summary className='w-fit cursor-pointer rounded text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary'>家长协助与学习记录</summary>
      <p className='mt-3 text-sm leading-6 text-muted-foreground'>整理资料与记录实际作答分开进行。看过讲解或得到提示，也可以如实记录。</p>
      <div className='mt-3 flex flex-wrap gap-2'>
        {canWrite ? <Button type='button' variant='outline' onClick={onMaterials}>整理学习资料</Button> : null}
        {canWrite && learnerName ? <Button type='button' variant='outline' onClick={onRecord}>记录一次作答</Button> : null}
        <Button type='button' variant='ghost' onClick={onHistory}>查看学习记录</Button>
      </div>
    </details>
  </section>
}
