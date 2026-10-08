import { Spinner } from './SearchBar'

function formatDuration(seconds) {
  if (!seconds) return '--:--'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = String(seconds % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${s}` : `${m}:${s}`
}

export function ResultCard({ song, onGenerate, busy, selected, index }) {
  return (
    <article
      style={{ animationDelay: `${index * 60}ms` }}
      className={`group animate-float-in flex flex-col overflow-hidden rounded-2xl border bg-white/[0.04] backdrop-blur-xl transition duration-300 hover:-translate-y-1 hover:border-accent/40 hover:bg-white/[0.07] ${
        selected ? 'border-accent/60 ring-1 ring-accent/30' : 'border-white/10'
      }`}
    >
      <div className="relative aspect-video overflow-hidden bg-white/5">
        {song.thumbnail_url && (
          <img
            src={song.thumbnail_url}
            alt=""
            loading="lazy"
            className="h-full w-full object-cover transition duration-500 group-hover:scale-105"
          />
        )}
        <span className="absolute bottom-2 right-2 rounded-md bg-black/70 px-2 py-0.5 text-xs font-medium tabular-nums">
          {formatDuration(song.duration)}
        </span>
      </div>
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="min-h-[3.25rem]">
          <h3 className="line-clamp-2 text-sm font-semibold leading-snug" title={song.title}>
            {song.title}
          </h3>
          <p className="mt-1 truncate text-xs text-white/50">{song.uploader || 'Canal desconhecido'}</p>
        </div>
        <button
          id={`generate-${song.id}`}
          onClick={() => onGenerate(song)}
          disabled={busy}
          className="mt-auto inline-flex items-center justify-center gap-2 rounded-xl border border-accent/30 bg-accent/10 px-4 py-2.5 text-sm font-semibold text-accent transition hover:bg-accent hover:text-ink active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-accent/10 disabled:hover:text-accent"
        >
          {selected && busy ? (
            <>
              <Spinner className="h-4 w-4" /> Gerando…
            </>
          ) : (
            <>
              <span aria-hidden="true">🎤</span> Gerar Karaokê
            </>
          )}
        </button>
      </div>
    </article>
  )
}

export function ResultSkeleton() {
  return (
    <div className="overflow-hidden rounded-2xl border border-white/10 bg-white/[0.04]">
      <div className="aspect-video animate-shimmer bg-[linear-gradient(90deg,transparent,rgb(255_255_255/0.08),transparent)] bg-[length:200%_100%]" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-4/5 rounded bg-white/10" />
        <div className="h-3 w-1/2 rounded bg-white/10" />
        <div className="h-10 rounded-xl bg-white/10" />
      </div>
    </div>
  )
}
