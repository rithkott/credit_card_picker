import { useRef, useState } from 'react'

/** Multi-file picker + drag-drop target for statement exports. Reads nothing
 * itself — hands File objects up and lets the lib do the work. While a batch
 * is parsing, `progress` shows a per-file progress bar but the target keeps
 * accepting drops — new files join the running batch. With `addMore` (review
 * screen) it renders as a slim strip for topping up the import. */
export function FileDrop({ progress, addMore = false, onFiles }: {
  progress: { done: number; total: number; current?: string } | null
  addMore?: boolean
  onFiles: (files: File[]) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)
  const parsing = progress !== null

  return (
    <div
      className={`filedrop${dragging ? ' dragging' : ''}${addMore ? ' add-more' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragging(true) }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        onFiles([...e.dataTransfer.files])
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
      {parsing ? (
        <div className="parse-progress">
          <span className="status">
            Uploading and parsing… {Math.min(progress.done + 1, progress.total)} of {progress.total}
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
          <span className="status">
            Keep dropping files — they join this batch.
          </span>
        </div>
      ) : (
        <>
          <div className="choose">
            <button type="button" onClick={() => inputRef.current?.click()}>
              {addMore ? 'Add more files' : 'Choose files'}
            </button>
            {!addMore && <span className="formats">CSV · OFX/QFX · PDF</span>}
          </div>
          <span className="status">
            {addMore
              ? 'or drop them here — they are added to the import below'
              : 'or drop them here — several months and cards at once works best'}
          </span>
        </>
      )}
    </div>
  )
}
