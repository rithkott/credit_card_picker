/** First-run wizard shell (v1.9.0): shows the existing form sections one group
 * at a time. Free navigation — Next is never gated; only the final action is
 * gated by canFinish (= no blocking validation errors, mirroring the Run gate).
 * The final button both completes the wizard and runs the optimizer (v1.11.1),
 * so its label is caller-supplied ("Run the numbers"). Reuses the section
 * components untouched; each step's node is built in Home. */

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
  finishLabel: string
  onBack: () => void
  onNext: () => void
  onFinish: () => void
  onJump: (index: number) => void
}

export function WizardShell({ steps, index, canFinish, finishLabel, onBack, onNext, onFinish, onJump }: Props) {
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
              <button
                type="button"
                className="wizard-dot-btn"
                onClick={() => onJump(i)}
                aria-label={`Go to step ${i + 1}: ${s.title}`}
              >
                <span className="dot" aria-hidden="true" />
                <span className="wizard-dot-label">{s.title}</span>
              </button>
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
            {finishLabel}
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
