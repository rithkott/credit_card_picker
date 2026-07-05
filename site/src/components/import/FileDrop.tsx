import { useRef, useState } from 'react'

/** Multi-file picker + drag-drop target for statement exports. Reads nothing
 * itself — hands File objects up and lets the lib do the work. */
export function FileDrop({ parsing, onFiles }: {
  parsing: boolean
  onFiles: (files: File[]) => void
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

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
      {parsing ? (
        <span className="status">Reading statements in your browser…</span>
      ) : (
        <>
          <button type="button" onClick={() => inputRef.current?.click()}>
            Choose statement files
          </button>
          <span className="status">or drop them here — several months and cards at once is best</span>
        </>
      )}
    </div>
  )
}
