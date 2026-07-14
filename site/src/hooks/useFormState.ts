/** Owns all persisted input-form state (v1.9.0) and mirrors it to localStorage.
 * Extracted from Home so the section components keep the exact same setters they
 * already receive (setSpend, setUser, …) — nothing about their prop wiring
 * changes. Lazy-inits from persistence once; a returning visitor lands in the
 * scrolling 'edit' view, a first-timer in the step-by-step 'wizard' view. Run
 * results stay local to Home (not persisted). */

import { useEffect, useRef, useState } from 'react'
import type { Unit } from '../lib/money'
import type { SpendState } from '../lib/validation'
import type { UserState } from '../lib/profile'
import type { Config } from '../types'
import { clearForm, loadForm, saveForm, type PersistedForm } from '../lib/persistence'

export type FormView = 'start' | 'wizard' | 'edit'
type Mode = 'auto' | 'manual'

/** Matches the current inline defaults in Home (pre-v1.9.0). Fresh visitors
 * additionally get optimize_for/accepts_brand_lockin re-seeded from the server
 * config in Home; reset() folds those in directly. */
function defaultSpend(): SpendState {
  return { categoryCents: {}, merchantCents: {}, categoryExtraCents: {}, merchantExtraCents: {} }
}
function defaultUser(): UserState {
  return {
    credit_tier: 'excellent',
    optimize_for: 'ongoing',
    accepts_brand_lockin: false,
    rewardKinds: { cashback: false, points: false },
    confirmed_usage: new Set(),
  }
}

export interface FormState {
  spend: SpendState
  setSpend: React.Dispatch<React.SetStateAction<SpendState>>
  user: UserState
  setUser: React.Dispatch<React.SetStateAction<UserState>>
  unit: Unit
  setUnit: React.Dispatch<React.SetStateAction<Unit>>
  mode: Mode
  setMode: React.Dispatch<React.SetStateAction<Mode>>
  selected: Set<string>
  setSelected: React.Dispatch<React.SetStateAction<Set<string>>>
  view: FormView
  setView: React.Dispatch<React.SetStateAction<FormView>>
  completed: boolean
  setCompleted: React.Dispatch<React.SetStateAction<boolean>>
  /** True when this mount restored a persisted blob — used by Home to skip the
   * config-defaults effect that would otherwise clobber restored values. */
  restored: boolean
  /** Wipe storage and reset every field to defaults merged with the server's
   * user_defaults, and drop back to the wizard. */
  reset: (defaults?: Config['user_defaults']) => void
}

export function useFormState(): FormState {
  // Read persistence exactly once for this mount.
  const loadedRef = useRef<PersistedForm | null | undefined>(undefined)
  if (loadedRef.current === undefined) loadedRef.current = loadForm()
  const loaded = loadedRef.current

  const [spend, setSpend] = useState<SpendState>(() => loaded?.spend ?? defaultSpend())
  const [user, setUser] = useState<UserState>(() => loaded?.user ?? defaultUser())
  const [unit, setUnit] = useState<Unit>(() => loaded?.unit ?? 'monthly')
  const [mode, setMode] = useState<Mode>(() => loaded?.mode ?? 'auto')
  const [selected, setSelected] = useState<Set<string>>(() => loaded?.selected ?? new Set())
  const [completed, setCompleted] = useState<boolean>(() => loaded?.completed ?? false)
  // Fresh visitor: land on the start splash (v1.9.1). Returning-but-unfinished
  // visitor (restored a blob mid-wizard) skips the splash and resumes the wizard;
  // a completed visitor goes straight to the scrolling edit view.
  const [view, setView] = useState<FormView>(() =>
    loaded?.completed ? 'edit' : loaded ? 'wizard' : 'start',
  )
  const [restored] = useState(() => loaded !== null)

  // Persist on change. Skip the mount pass so a visitor who never touches the
  // form leaves no stored blob behind.
  const firstPass = useRef(true)
  useEffect(() => {
    if (firstPass.current) {
      firstPass.current = false
      return
    }
    saveForm({ unit, mode, spend, user, selected, completed })
  }, [unit, mode, spend, user, selected, completed])

  const reset = (defaults?: Config['user_defaults']) => {
    clearForm()
    setSpend(defaultSpend())
    setUser({
      ...defaultUser(),
      ...(defaults
        ? { optimize_for: defaults.optimize_for, accepts_brand_lockin: defaults.accepts_brand_lockin }
        : {}),
    })
    setUnit('monthly')
    setMode('auto')
    setSelected(new Set())
    setCompleted(false)
    setView('wizard')
  }

  return {
    spend, setSpend,
    user, setUser,
    unit, setUnit,
    mode, setMode,
    selected, setSelected,
    view, setView,
    completed, setCompleted,
    restored,
    reset,
  }
}
