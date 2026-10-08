import { useState } from 'react'

export default function SearchBar({ onSearch, loading }) {
  const [value, setValue] = useState('')

  const submit = (e) => {
    e.preventDefault()
    const q = value.trim()
    if (q && !loading) onSearch(q)
  }

  return (
    <form onSubmit={submit} className="relative mx-auto flex w-full max-w-2xl items-center" role="search">
      <div className="pointer-events-none absolute -inset-px rounded-2xl bg-gradient-to-r from-violet/40 via-transparent to-accent/40 opacity-60 blur-md" />
      <div className="relative flex w-full items-center gap-2 rounded-2xl border border-white/10 bg-white/[0.06] p-2 pl-5 backdrop-blur-xl transition focus-within:border-accent/50">
        <svg viewBox="0 0 24 24" className="h-5 w-5 shrink-0 text-white/40" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <path d="m20 20-3.5-3.5" strokeLinecap="round" />
        </svg>
        <input
          id="search-input"
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder="Nome da música ou artista…"
          aria-label="Nome da música"
          className="min-w-0 flex-1 bg-transparent py-2 text-base text-white placeholder:text-white/35 focus:outline-none"
        />
        <button
          id="search-button"
          type="submit"
          disabled={loading || !value.trim()}
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet to-accent px-5 py-2.5 text-sm font-semibold text-ink transition hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {loading && <Spinner className="h-4 w-4" />}
          {loading ? 'Buscando' : 'Buscar'}
        </button>
      </div>
    </form>
  )
}

export function Spinner({ className = 'h-5 w-5' }) {
  return (
    <svg className={`${className} animate-spin`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}
