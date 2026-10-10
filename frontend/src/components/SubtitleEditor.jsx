import { useEffect, useMemo, useState } from 'react'
import { getSubtitles, updateSubtitles } from '../api'

function fmtTime(sec) {
  if (sec == null || isNaN(sec)) return '00:00.00'
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const cs = Math.floor((sec % 1) * 100)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${String(cs).padStart(2, '0')}`
}

export default function SubtitleEditor({ job, onCancel, onRerenderStarted, onSeekVideo }) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [verses, setVerses] = useState([])
  const [search, setSearch] = useState('')
  const [expandedVerse, setExpandedVerse] = useState(null)

  useEffect(() => {
    let active = true
    async function load() {
      setLoading(true)
      setError(null)
      try {
        const data = await getSubtitles(job.job_id)
        if (active) {
          setVerses(data.verses || [])
        }
      } catch (err) {
        if (active) setError(err.message)
      } finally {
        if (active) setLoading(false)
      }
    }
    load()
    return () => {
      active = false
    }
  }, [job.job_id])

  // Recalcula start e end do verso com base nas palavras
  const updateVerseWords = (vIndex, newWords) => {
    setVerses((prev) =>
      prev.map((v, i) => {
        if (i !== vIndex) return v
        const sorted = [...newWords].sort((a, b) => a.start - b.start)
        const start = sorted.length ? sorted[0].start : v.start
        const end = sorted.length ? sorted[sorted.length - 1].end : v.end
        const text = sorted.map((w) => w.word).join(' ')
        return { ...v, words: sorted, start, end, text }
      })
    )
  }

  // Ajusta o offset de tempo (delta) para um verso inteiro
  const shiftVerseTime = (vIndex, delta) => {
    setVerses((prev) =>
      prev.map((v, i) => {
        if (i !== vIndex) return v
        const updatedWords = v.words.map((w) => ({
          ...w,
          start: Math.max(0, +(w.start + delta).toFixed(2)),
          end: Math.max(0.05, +(w.end + delta).toFixed(2)),
        }))
        const start = updatedWords.length ? updatedWords[0].start : Math.max(0, +(v.start + delta).toFixed(2))
        const end = updatedWords.length ? updatedWords[updatedWords.length - 1].end : Math.max(0.05, +(v.end + delta).toFixed(2))
        return { ...v, words: updatedWords, start, end }
      })
    )
  }

  // Deslocamento global (adianta ou atrasa toda a música)
  const shiftAllVerses = (delta) => {
    setVerses((prev) =>
      prev.map((v) => {
        const updatedWords = v.words.map((w) => ({
          ...w,
          start: Math.max(0, +(w.start + delta).toFixed(2)),
          end: Math.max(0.05, +(w.end + delta).toFixed(2)),
        }))
        const start = updatedWords.length ? updatedWords[0].start : Math.max(0, +(v.start + delta).toFixed(2))
        const end = updatedWords.length ? updatedWords[updatedWords.length - 1].end : Math.max(0.05, +(v.end + delta).toFixed(2))
        return { ...v, words: updatedWords, start, end }
      })
    )
  }

  // Atualização direta do texto do verso
  const handleVerseTextChange = (vIndex, newText) => {
    setVerses((prev) =>
      prev.map((v, i) => {
        if (i !== vIndex) return v
        const oldWords = v.words || []
        const splitted = newText.trim() ? newText.trim().split(/\s+/) : []
        let newWords = []

        if (splitted.length === oldWords.length) {
          // Mantém os tempos exatos palavra por palavra
          newWords = oldWords.map((w, idx) => ({ ...w, word: splitted[idx] }))
        } else if (splitted.length > 0) {
          // Redistribui uniformemente no intervalo do verso
          const vStart = v.start
          const vEnd = Math.max(v.start + 0.5, v.end)
          const step = (vEnd - vStart) / splitted.length
          newWords = splitted.map((word, idx) => ({
            word,
            start: +(vStart + idx * step).toFixed(2),
            end: +(vStart + (idx + 1) * step).toFixed(2),
          }))
        }
        return {
          ...v,
          text: newText,
          words: newWords,
        }
      })
    )
  }

  // Edita uma palavra individual
  const handleWordFieldChange = (vIndex, wIndex, field, value) => {
    setVerses((prev) =>
      prev.map((v, i) => {
        if (i !== vIndex) return v
        const updatedWords = v.words.map((w, j) => {
          if (j !== wIndex) return w
          return {
            ...w,
            [field]: field === 'word' ? value : Math.max(0, Number(value) || 0),
          }
        })
        const text = updatedWords.map((w) => w.word).join(' ')
        const start = updatedWords.length ? Math.min(...updatedWords.map((w) => w.start)) : v.start
        const end = updatedWords.length ? Math.max(...updatedWords.map((w) => w.end)) : v.end
        return { ...v, words: updatedWords, text, start, end }
      })
    )
  }

  // Remove uma palavra do verso
  const handleDeleteWord = (vIndex, wIndex) => {
    const v = verses[vIndex]
    const updated = v.words.filter((_, idx) => idx !== wIndex)
    updateVerseWords(vIndex, updated)
  }

  // Adiciona uma palavra no final do verso
  const handleAddWord = (vIndex) => {
    const v = verses[vIndex]
    const lastWord = v.words[v.words.length - 1]
    const start = lastWord ? lastWord.end : v.start
    const end = +(start + 0.5).toFixed(2)
    const updated = [...v.words, { word: 'palavra', start, end }]
    updateVerseWords(vIndex, updated)
  }

  // Remove um verso inteiro
  const handleDeleteVerse = (vIndex) => {
    setVerses((prev) => prev.filter((_, idx) => idx !== vIndex))
  }

  // Salvar e regerar o karaokê
  const handleSaveAndRerender = async () => {
    const allWords = []
    for (const v of verses) {
      let isFirst = true
      for (const w of v.words) {
        if (w.word && w.word.trim()) {
          allWords.push({
            start: +w.start,
            end: Math.max(+w.start + 0.05, +w.end),
            word: w.word.trim(),
            ...(isFirst ? { is_verse_start: true } : {}),
          })
          isFirst = false
        }
      }
    }

    if (allWords.length === 0) {
      alert('A legenda precisa ter pelo menos uma palavra válida!')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const updatedJob = await updateSubtitles(job.job_id, allWords)
      onRerenderStarted(updatedJob)
    } catch (err) {
      setError(err.message)
      setSaving(false)
    }
  }

  const filteredVerses = useMemo(() => {
    if (!search.trim()) return verses
    const q = search.toLowerCase()
    return verses.filter((v) => v.text.toLowerCase().includes(q))
  }, [verses, search])

  const totalWords = useMemo(() => {
    return verses.reduce((sum, v) => sum + (v.words?.length || 0), 0)
  }, [verses])

  return (
    <div className="flex flex-col gap-5 rounded-3xl border border-accent/40 bg-zinc-950/80 p-5 backdrop-blur-2xl sm:p-7">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-white/10 pb-5">
        <div>
          <div className="flex items-center gap-2">
            <span className="flex h-2.5 w-2.5 rounded-full bg-accent animate-pulse" />
            <span className="text-xs font-semibold uppercase tracking-wider text-accent">
              Editor de Legendas
            </span>
          </div>
          <h3 className="mt-1 text-xl font-bold text-white sm:text-2xl">
            Ajustar Letra e Sincronização
          </h3>
          <p className="mt-1 text-xs text-white/50 sm:text-sm">
            Edite as frases, corrija palavras ou altere o tempo de exibição na tela.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onCancel}
            disabled={saving}
            className="rounded-xl border border-white/15 px-4 py-2 text-sm font-medium text-white/70 transition hover:bg-white/10 hover:text-white disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSaveAndRerender}
            disabled={saving || loading || verses.length === 0}
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-accent to-lime-400 px-5 py-2.5 text-sm font-bold text-zinc-950 shadow-lg shadow-accent/20 transition hover:brightness-110 active:scale-95 disabled:opacity-50"
          >
            {saving ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                Regerando Vídeo...
              </>
            ) : (
              <>
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5">
                  <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                Salvar e Regerar Karaokê
              </>
            )}
          </button>
        </div>
      </div>

      {error && (
        <div role="alert" className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {/* Global Controls & Search Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-white/[0.03] p-3 border border-white/5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-white/60">Ajuste global do tempo:</span>
          <div className="flex items-center gap-1">
            {[-0.5, -0.2, -0.1, 0.1, 0.2, 0.5].map((delta) => (
              <button
                key={delta}
                type="button"
                onClick={() => shiftAllVerses(delta)}
                className="rounded-lg bg-white/5 px-2.5 py-1 text-xs font-mono font-medium text-white/80 transition hover:bg-accent/20 hover:text-accent active:scale-95"
                title={`Desloca todos os versos em ${delta > 0 ? '+' : ''}${delta}s`}
              >
                {delta > 0 ? `+${delta}` : delta}s
              </button>
            ))}
          </div>
        </div>

        <div className="relative min-w-[220px]">
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filtrar por texto..."
            className="w-full rounded-xl border border-white/10 bg-black/40 px-3 py-1.5 pl-8 text-xs text-white placeholder-white/30 focus:border-accent focus:outline-none"
          />
          <svg className="absolute left-2.5 top-2.5 h-3.5 w-3.5 text-white/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <path d="m21 21-4.3-4.3" />
          </svg>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center gap-3 py-16">
          <svg className="h-8 w-8 animate-spin text-accent" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
          </svg>
          <p className="text-sm text-white/50">Carregando transcrição e versos...</p>
        </div>
      ) : verses.length === 0 ? (
        <p className="py-8 text-center text-sm text-white/50">Nenhuma palavra encontrada para este karaokê.</p>
      ) : (
        <div className="flex flex-col gap-3 max-h-[550px] overflow-y-auto pr-1">
          {filteredVerses.map((v, originalIdx) => {
            const vIndex = verses.indexOf(v)
            const isExpanded = expandedVerse === vIndex

            return (
              <div
                key={vIndex}
                className="group flex flex-col gap-3 rounded-2xl border border-white/5 bg-white/[0.02] p-4 transition hover:border-white/15 hover:bg-white/[0.04]"
              >
                {/* Verse Header */}
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-lg bg-accent/15 text-xs font-bold text-accent">
                      {vIndex + 1}
                    </span>
                    <span className="font-mono text-xs font-medium text-white/60">
                      {fmtTime(v.start)} → {fmtTime(v.end)}
                    </span>
                    <span className="text-[11px] text-white/35">
                      ({(v.end - v.start).toFixed(1)}s • {v.words.length} palavras)
                    </span>
                  </div>

                  <div className="flex items-center gap-1.5">
                    {onSeekVideo && (
                      <button
                        type="button"
                        onClick={() => onSeekVideo(v.start)}
                        className="flex items-center gap-1 rounded-lg bg-white/5 px-2 py-1 text-xs text-white/70 transition hover:bg-accent/20 hover:text-accent"
                        title="Tocar este verso no vídeo"
                      >
                        <svg viewBox="0 0 24 24" className="h-3 w-3 fill-current">
                          <polygon points="5 3 19 12 5 21 5 3" />
                        </svg>
                        Ouvir
                      </button>
                    )}

                    {/* Offset per verse */}
                    <div className="hidden sm:flex items-center gap-1 pl-2 border-l border-white/10">
                      <span className="text-[10px] text-white/40">Offset:</span>
                      {[-0.2, -0.1, 0.1, 0.2].map((delta) => (
                        <button
                          key={delta}
                          type="button"
                          onClick={() => shiftVerseTime(vIndex, delta)}
                          className="rounded bg-white/5 px-1.5 py-0.5 text-[10px] font-mono text-white/60 hover:bg-accent/20 hover:text-accent"
                        >
                          {delta > 0 ? `+${delta}` : delta}
                        </button>
                      ))}
                    </div>

                    <button
                      type="button"
                      onClick={() => setExpandedVerse(isExpanded ? null : vIndex)}
                      className={`ml-1 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                        isExpanded
                          ? 'bg-accent/20 text-accent'
                          : 'bg-white/5 text-white/60 hover:bg-white/10 hover:text-white'
                      }`}
                    >
                      {isExpanded ? 'Ocultar Palavras' : 'Palavras Detalhadas'}
                    </button>

                    <button
                      type="button"
                      onClick={() => handleDeleteVerse(vIndex)}
                      className="rounded-lg p-1 text-white/30 hover:bg-red-500/20 hover:text-red-300"
                      title="Excluir verso"
                    >
                      <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M3 6h18m-2 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
                      </svg>
                    </button>
                  </div>
                </div>

                {/* Verse Text Input */}
                <div>
                  <input
                    type="text"
                    value={v.text}
                    onChange={(e) => handleVerseTextChange(vIndex, e.target.value)}
                    className="w-full rounded-xl border border-white/10 bg-black/50 px-3.5 py-2 text-sm text-white font-medium focus:border-accent focus:bg-black/80 focus:outline-none"
                    placeholder="Texto do verso..."
                  />
                </div>

                {/* Expanded Word-by-word Breakdown */}
                {isExpanded && (
                  <div className="flex flex-col gap-2 rounded-xl bg-black/40 p-3 border border-white/5 animate-fade-in">
                    <div className="grid grid-cols-[1fr_80px_80px_32px] gap-2 px-1 text-[11px] font-medium text-white/40">
                      <span>Palavra</span>
                      <span>Início (s)</span>
                      <span>Fim (s)</span>
                      <span />
                    </div>

                    <div className="flex flex-col gap-1.5">
                      {v.words.map((w, wIndex) => (
                        <div key={wIndex} className="grid grid-cols-[1fr_80px_80px_32px] gap-2 items-center">
                          <input
                            type="text"
                            value={w.word}
                            onChange={(e) => handleWordFieldChange(vIndex, wIndex, 'word', e.target.value)}
                            className="rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white focus:border-accent focus:outline-none"
                          />
                          <input
                            type="number"
                            step="0.05"
                            value={w.start}
                            onChange={(e) => handleWordFieldChange(vIndex, wIndex, 'start', e.target.value)}
                            className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs font-mono text-white/90 focus:border-accent focus:outline-none"
                          />
                          <input
                            type="number"
                            step="0.05"
                            value={w.end}
                            onChange={(e) => handleWordFieldChange(vIndex, wIndex, 'end', e.target.value)}
                            className="rounded-lg border border-white/10 bg-white/5 px-2 py-1 text-xs font-mono text-white/90 focus:border-accent focus:outline-none"
                          />
                          <button
                            type="button"
                            onClick={() => handleDeleteWord(vIndex, wIndex)}
                            className="flex h-7 w-7 items-center justify-center rounded-lg text-white/30 hover:bg-red-500/20 hover:text-red-300"
                            title="Remover palavra"
                          >
                            ×
                          </button>
                        </div>
                      ))}
                    </div>

                    <div className="mt-2 flex justify-start">
                      <button
                        type="button"
                        onClick={() => handleAddWord(vIndex)}
                        className="flex items-center gap-1 rounded-lg border border-dashed border-white/20 px-3 py-1 text-xs text-white/60 hover:border-accent hover:text-accent"
                      >
                        + Adicionar palavra
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Footer Info */}
      <div className="flex items-center justify-between border-t border-white/10 pt-4 text-xs text-white/40">
        <span>Total: {verses.length} versos ({totalWords} palavras)</span>
        <span>A alteração re-renderizará o vídeo final sem refazer o áudio.</span>
      </div>
    </div>
  )
}
