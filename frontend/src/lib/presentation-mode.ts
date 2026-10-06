export type PresentationMode = 'student' | 'parent'
const key = (username: string) => `swb:presentation:${encodeURIComponent(username)}`
export function readPresentationMode(username: string): PresentationMode {
  try { return localStorage.getItem(key(username)) === 'parent' ? 'parent' : 'student' } catch { return 'student' }
}
export function savePresentationMode(username: string, value: PresentationMode) {
  try { localStorage.setItem(key(username), value) } catch { /* Preference failure does not block navigation. */ }
}
