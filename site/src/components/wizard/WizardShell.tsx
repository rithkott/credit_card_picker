/** First-run wizard shell (v1.9.0): shows the existing form sections one group
 * at a time. Free navigation — Next is never gated; only the final Finish is
 * gated by canFinish (= no blocking validation errors, mirroring the Run gate).
 * Reuses the section components untouched; each step's node is built in Home. */

import type { ReactNode } from 'react'

export interface WizardStep {
  id: string
  title: string
  node: ReactNode
}

interface Props {
  steps: WizardStep[]
  index: number
  canFinish: boolean
  onBack: () => void
  onNext: () => void
  onFinish: () => void
}

export function WizardShell({ steps, index, canFinish, onBack, onNext, onFinish }: Props) {
  const step = steps[index]
  const isLast = index === steps.length - 1

  return (
    <div className="wizard">
      <div className="wizard-progress" role="group" aria-label="Progress">
        <span className="wizard-count">
          Step {index + 1} of {steps.length}
        </span>
        <ol className="wizard-dots">
          {steps.map((s, i) => (
            <li
              key={s.id}
              className={i === index ? 'current' : i < index ? 'done' : ''}
              aria-current={i === index ? 'step' : undefined}
            >
              <span className="dot" aria-hidden="true" />
              <span className="wizard-dot-label">{s.title}</span>
            </li>
          ))}
        </ol>
      </div>

      <div className="wizard-step" key={step.id}>
        {step.node}
      </div>

      <div className="wizard-nav">
        <button type="button" className="ghost" onClick={onBack} disabled={index === 0}>
          Back
        </button>
        {isLast ? (
          <button type="button" className="primary" onClick={onFinish} disabled={!canFinish}>
            Finish
          </button>
        ) : (
          <button type="button" className="primary" onClick={onNext}>
            Next
          </button>
        )}
      </div>
    </div>
  )
}
