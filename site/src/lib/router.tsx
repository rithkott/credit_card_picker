/** Minimal history router — 4 static routes don't justify a dependency.
 * usePath() re-renders on navigation; <Link> pushes history and scrolls to
 * top (content pages are long; landing mid-page reads as a broken jump). */
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { MouseEvent, ReactNode } from 'react'

const PathContext = createContext<string>('/')
const NavigateContext = createContext<(to: string) => void>(() => {})

export function Router({ children }: { children: ReactNode }) {
  const [path, setPath] = useState(window.location.pathname)

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const navigate = useCallback((to: string) => {
    if (to === window.location.pathname) return
    window.history.pushState(null, '', to)
    setPath(to)
    window.scrollTo(0, 0)
  }, [])

  return (
    <NavigateContext.Provider value={navigate}>
      <PathContext.Provider value={path}>{children}</PathContext.Provider>
    </NavigateContext.Provider>
  )
}

export function usePath(): string {
  return useContext(PathContext)
}

export function Link({ to, className, children }: {
  to: string
  className?: string
  children: ReactNode
}) {
  const navigate = useContext(NavigateContext)
  const onClick = (e: MouseEvent<HTMLAnchorElement>) => {
    // Let cmd/ctrl/shift-click and middle-click open a new tab natively.
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || e.button !== 0) return
    e.preventDefault()
    navigate(to)
  }
  return (
    <a href={to} className={className} onClick={onClick}>
      {children}
    </a>
  )
}
