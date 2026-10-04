import { describe, expect, it } from 'vitest'
import { fragmentOfPath, householdIdForBusinessPath, isFilePath, learnerIdForBusinessPath, parseRoute, previewKindForPath, printReportPathForLearner, routeForBusinessPath, routeUrl, screenForView, safeBusinessPath, withoutFragment } from './routes'

describe('app routing', () => {
  it('round-trips the selected page and household, learner, and business screen through the URL', () => {
    const route = {
      view: 'knowledge' as const,
      household: 'family 1',
      learner: 'learner-7',
      screen: '/knowledge/entity/12/?household_id=family%201',
    }

    expect(parseRoute(new URL(routeUrl(route), 'https://study.test'))).toEqual(route)
  })

  it('restores learner context from the embedded business screen when outer state omits it', () => {
    const profile = parseRoute(new URL(routeUrl({
      view: 'learning', household: 'home-1', learner: '', screen: '/learning/profile/learner-b/',
    }), 'https://study.test'))
    expect(profile).toMatchObject({ household: 'home-1', learner: 'learner-b', screen: '/learning/profile/learner-b/' })

    const index = parseRoute(new URL(routeUrl({
      view: 'learning', household: 'home-1', learner: '', screen: '/learning/?household=home-1&learner=learner-b',
    }), 'https://study.test'))
    expect(index.learner).toBe('learner-b')
  })

  it('keeps same-origin business paths and rejects external, protocol, and backslash targets', () => {
    expect(safeBusinessPath('/knowledge/?household_id=1', 'https://study.test')).toBe('/knowledge/?household_id=1')
    expect(safeBusinessPath('https://outside.test/knowledge/', 'https://study.test')).toBeNull()
    expect(safeBusinessPath('//outside.test/knowledge/', 'https://study.test')).toBeNull()
    expect(safeBusinessPath('/knowledge/\\..\\accounts/', 'https://study.test')).toBeNull()
  })

  it('preserves anchor fragments and cross-household context changes', () => {
    const route = { view: 'learning' as const, household: 'home-a', learner: 'learner-a', screen: '/learning/attempt/old/' }
    expect(safeBusinessPath('/learning/attempt/old/#revision-2', 'https://study.test')).toBe('/learning/attempt/old/#revision-2')
    expect(withoutFragment('/learning/attempt/old/?mode=review#revision-2')).toBe('/learning/attempt/old/?mode=review')
    expect(fragmentOfPath('/learning/attempt/old/#revision-2')).toBe('#revision-2')
    expect(routeForBusinessPath('/learning/attempt/new/?household_id=home-b#revision-4', route)).toEqual({
      ...route, household: 'home-b', learner: '', screen: '/learning/attempt/new/?household_id=home-b#revision-4',
    })
    expect(routeForBusinessPath('/app/?view=learning&household=home-b&screen=%2Flearning%2Fattempt%2Fnew%2F', route))
      .toEqual({ view: 'learning', household: 'home-b', learner: '', screen: '/learning/attempt/new/' })
  })

  it('classifies framework images and PDFs for in-app preview', () => {
    expect(previewKindForPath('/page/123e4567-e89b-12d3-a456-426614174000/preview/90/')).toBe('image')
    expect(previewKindForPath('/derivative/123e4567-e89b-12d3-a456-426614174000/')).toBe('image')
    expect(previewKindForPath('/prints/snapshots/12/answers.pdf')).toBe('pdf')
    expect(previewKindForPath('/prints/snapshots/12/document.pdf/')).toBe('pdf')
    expect(previewKindForPath('/prints/diagrams/files/12/png/')).toBe('image')
    expect(previewKindForPath('/prints/diagrams/files/12/vector/')).toBeNull()
    expect(isFilePath('/prints/snapshots/12/document.docx/')).toBe(true)
    expect(isFilePath('/prints/diagrams/files/12/vector/')).toBe(true)
    expect(previewKindForPath('/downloads/study.zip')).toBeNull()
  })

  it('uses the learner page for profile links and the progress page for schedule links', () => {
    const route = { view: 'overview' as const, household: 'home-1', learner: 'learner-1', screen: '' }
    expect(routeForBusinessPath('/learning/profile/learner-1/', route)?.view).toBe('learning')
    expect(routeForBusinessPath('/learning/schedules/3/', route)?.view).toBe('progress')
    expect(routeForBusinessPath('/study/', route)?.view).toBe('progress')
    expect(routeForBusinessPath('/study/learner/1/report/', route)?.view).toBe('progress')
    expect(routeForBusinessPath('/catalogue/question/3/', route)?.view).toBe('knowledge')
    expect(routeForBusinessPath('/help/', route)?.view).toBe('settings')
    expect(routeForBusinessPath('//outside.test/path', route)).toBeNull()
    expect(routeForBusinessPath('/prints/snapshots/3/result.pdf', route)).toBeNull()
    expect(isFilePath('/study/learner/4/report.json')).toBe(true)
  })

  it('tracks learner context from profile paths and explicit learner queries', () => {
    const route = { view: 'learning' as const, household: 'home-1', learner: 'learner-1', screen: '/learning/' }
    expect(routeForBusinessPath('/learning/profile/learner-2/attempts/?household=home-1', route)).toEqual({
      view: 'learning', household: 'home-1', learner: 'learner-2',
      screen: '/learning/profile/learner-2/attempts/?household=home-1',
    })
    expect(routeForBusinessPath('/learning/profile/new/', route)?.learner).toBe('learner-1')
    expect(routeForBusinessPath('/learning/?household=home-1&learner=learner-2', route)?.learner).toBe('learner-2')
    expect(routeForBusinessPath('/learning/?household=home-2&learner=learner-2', route)).toEqual({
      view: 'learning', household: 'home-2', learner: 'learner-2',
      screen: '/learning/?household=home-2&learner=learner-2',
    })
    expect(routeForBusinessPath('/knowledge/?household=home-2', route)?.learner).toBe('')
  })

  it('maps study and print report paths through the validated learner report URLs', () => {
    const learners = [
      { id: 'learner-a', report_url: '/study/learner/11/report/' },
      { id: 'learner-b', report_url: '/study/learner/22/report/' },
    ]
    const route = { view: 'progress' as const, household: 'home-1', learner: 'learner-a', screen: '/study/' }
    expect(learnerIdForBusinessPath('/study/learner/22/report/', learners)).toBe('learner-b')
    expect(learnerIdForBusinessPath('/study/learner/22/schedule/new/', learners)).toBe('learner-b')
    expect(learnerIdForBusinessPath('/prints/reports/22/', learners)).toBe('learner-b')
    expect(routeForBusinessPath('/study/learner/22/report/', route, route.learner, learners)?.learner).toBe('learner-b')
    expect(printReportPathForLearner(learners[1].report_url)).toBe('/prints/reports/22/')
    expect(printReportPathForLearner('https://outside.test/study/learner/22/report/')).toBeNull()
  })

  it('maps household-specific operations and AI paths into route context', () => {
    const route = { view: 'settings' as const, household: 'home-1', learner: 'learner-1', screen: '/members/?household_id=home-1' }
    for (const path of [
      '/operations/household/home-2/retention/',
      '/ai/config/home-2/',
      '/ai/new/home-2/',
    ]) {
      expect(householdIdForBusinessPath(path)).toBe('home-2')
      expect(routeForBusinessPath(path, route)).toMatchObject({ household: 'home-2', learner: '', screen: path })
      const restored = parseRoute(new URL(routeUrl({ ...route, screen: path }), 'https://study.test'))
      expect(restored).toMatchObject({ household: 'home-2', learner: '', screen: path })
    }
    expect(routeForBusinessPath('/operations/household/home-2/retention/?household_id=home-1', route)?.household).toBe('home-2')
    expect(householdIdForBusinessPath('/ai/config/home%2F2/')).toBeNull()
    expect(householdIdForBusinessPath('https://outside.test/operations/household/home-2/retention/')).toBeNull()
  })

  it('provides scoped entry paths for the business sections', () => {
    expect(screenForView('knowledge', 'home-1')).toBe('/knowledge/?household_id=home-1')
    expect(screenForView('learning', 'home-1', 'learner-1')).toBe('/learning/?household=home-1&learner=learner-1')
    expect(screenForView('documents', 'home-1')).toBe('/prints/?household=home-1')
    expect(screenForView('settings', 'home-1')).toBe('/members/?household_id=home-1')
  })
})
