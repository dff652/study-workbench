import { describe, expect, it } from 'vitest'
import { knowledgeMaterialId, knowledgeScreen, parseRoute, routeForBusinessPath, routeUrl, solutionScreen } from './routes'

describe('knowledge mode and school subject routes', () => {
  const route = { view: 'materials' as const, household: 'home-1', learner: '', screen: '', materialId: 'material-1', materialQuery: '英语', materialPage: 3, materialSubject: 'english' }
  it('round trips subject and material filters through a reload URL', () => {
    expect(parseRoute(new URL(routeUrl(route), 'https://study.test'))).toEqual(route)
    expect(parseRoute(new URL('/app/?view=materials&subject=made-up', 'https://study.test')).materialSubject).toBeUndefined()
  })
  it('keeps the knowledge route separate from solutions and rejects invalid identifiers', () => {
    expect(knowledgeMaterialId(knowledgeScreen('material-1') + '?panel=outputs')).toBe('material-1')
    expect(knowledgeMaterialId(solutionScreen('material-1'))).toBeNull()
    expect(knowledgeMaterialId('/__app__/knowledge-explanations/a%2Fb/')).toBeNull()
    expect(routeForBusinessPath(knowledgeScreen('material-1'), route)?.view).toBe('knowledge')
  })
  it('drops filters when a business route changes household or leaves materials', () => {
    const next = routeForBusinessPath('/knowledge/?household_id=home-2', route)
    expect(next).toMatchObject({ view: 'knowledge', household: 'home-2' })
    expect(next?.materialSubject).toBeUndefined(); expect(next?.materialId).toBeUndefined()
  })
})
