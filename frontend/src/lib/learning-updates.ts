import { useEffect, useState } from 'react'

type LearningScope = { householdId: string; learnerId?: string }
const eventName = 'swb:learning-updated'

/** Publish only after an acknowledged save, with the owning family scope. */
export function notifyLearningUpdate(scope: LearningScope) {
  window.dispatchEvent(new CustomEvent<LearningScope>(eventName, { detail: scope }))
}

export function useLearningUpdates(householdId: string, learnerId?: string) {
  const [version, setVersion] = useState(0)
  useEffect(() => {
    const receive = (event: Event) => {
      const scope = (event as CustomEvent<LearningScope>).detail
      if (scope?.householdId === householdId && (!learnerId || !scope.learnerId || scope.learnerId === learnerId)) {
        setVersion((value) => value + 1)
      }
    }
    window.addEventListener(eventName, receive)
    return () => window.removeEventListener(eventName, receive)
  }, [householdId, learnerId])
  return version
}
