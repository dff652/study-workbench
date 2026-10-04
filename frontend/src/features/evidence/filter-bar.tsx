import { RefreshCw } from 'lucide-react'
import type { Filters, SourceKind } from '../../types'
import { INITIAL_FILTERS, SOURCE_LABELS } from '../../components/shared'
import { Button } from '../../components/ui/button'
import { Card, CardContent } from '../../components/ui/card'
import { SOURCE_KINDS } from '../../types'

export function FilterBar({ filters, onChange }: { filters: Filters; onChange: (filters: Filters) => void }) {
  return (
    <Card className='shadow-sm'>
      <CardContent className='grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-[minmax(9rem,0.8fr)_minmax(9rem,0.8fr)_minmax(13rem,1fr)_auto] sm:p-5'>
        <div>
          <label htmlFor='date-from' className='mb-1.5 block text-xs font-medium text-muted-foreground'>实际作答日期起</label>
          <input id='date-from' type='date' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={filters.dateFrom} onChange={(event) => onChange({ ...filters, dateFrom: event.target.value })} />
        </div>
        <div>
          <label htmlFor='date-to' className='mb-1.5 block text-xs font-medium text-muted-foreground'>实际作答日期止</label>
          <input id='date-to' type='date' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={filters.dateTo} onChange={(event) => onChange({ ...filters, dateTo: event.target.value })} />
        </div>
        <div>
          <label htmlFor='source-kind' className='mb-1.5 block text-xs font-medium text-muted-foreground'>作答来源</label>
          <select id='source-kind' className='h-10 w-full rounded-md border bg-background px-3 text-sm' value={filters.sourceKind} onChange={(event) => onChange({ ...filters, sourceKind: event.target.value as SourceKind | '' })}>
            <option value=''>全部来源</option>
            {SOURCE_KINDS.map((kind) => <option key={kind} value={kind}>{SOURCE_LABELS[kind]}</option>)}
          </select>
        </div>
        <div className='flex items-end'>
          <Button type='button' variant='outline' className='w-full' onClick={() => onChange(INITIAL_FILTERS)} disabled={!filters.dateFrom && !filters.dateTo && !filters.sourceKind}>
            <RefreshCw className='size-4' aria-hidden='true' />清除筛选
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}
