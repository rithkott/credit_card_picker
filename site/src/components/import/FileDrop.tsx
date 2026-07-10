import { useRef, useState } from 'react'

/** Multi-file picker + drag-drop target for statement exports. Reads nothing
 * itself — hands File objects up and lets the lib do the work. While a batch
 * is parsing, `progress` replaces the picker with a per-file progress bar. */
export function FileDrop({ progress, onFiles }: {
  progress: { done: number; total: number; current?: string } | null
  onFiles: (files: File[]) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const parsing = progress !== null

  return (
    <div
      className={`filedrop${dragging ? ' dragging' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (!parsing) onFiles([...e.dataTransfer.files])
      }}
    >
      <input
        ref={inputRef}
        type="file"
        multiple
        accept=".csv,.ofx,.qfx,.pdf,text/csv,application/pdf"
        style={{ display: 'none' }}
        onChange={(e) => {
          onFiles([...(e.target.files ?? [])])
          e.target.value = '' // same files can be re-picked after a discard
        }}
      />
      {progress !== null ? (
        <div className="parse-progress">
          <span className="status">
            Reading statements in your browser… {Math.min(progress.done + 1, progress.total)} of {progress.total}
          </span>
          <div
            className="parse-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={progress.total}
            aria-valuenow={progress.done}
          >
            <div
              className="parse-bar-fill"
              style={{ width: `${progress.total === 0 ? 0 : (progress.done / progress.total) * 100}%` }}
            />
          </div>
          {progress.current && <span className="parse-file">{progress.current}</span>}
        </div>
      ) : (
        <>
          <div className="choose">
            <button type="button" onClick={() => inputRef.current?.click()}>
              Choose files
            </button>
            <span className="formats">CSV · OFX/QFX · PDF</span>
          </div>
          <span className="status">
            or drop them here — several months and cards at once works best
          </span>
        </>
      )}
    </div>
  )
}
