import { afterEach, expect, it } from 'vitest'
import { readPresentationMode, savePresentationMode } from './presentation-mode'
afterEach(() => localStorage.clear())
it('defaults to student and never applies one account preference to another', () => {
  expect(readPresentationMode('student-a')).toBe('student')
  savePresentationMode('parent-a', 'parent')
  expect(readPresentationMode('parent-a')).toBe('parent')
  expect(readPresentationMode('student-a')).toBe('student')
  savePresentationMode('parent-a', 'student')
  expect(readPresentationMode('parent-a')).toBe('student')
})
