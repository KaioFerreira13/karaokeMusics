import { useEffect } from 'react'

export default function VideoPlayer({ job, onOpenEditor, videoRef }) {
  const baseVideoUrl = job.video_url ? job.video_url.split('?')[0] : ''
  const version = job.updated_at ? new Date(job.updated_at).getTime() : Date.now()
  const src = baseVideoUrl ? `${baseVideoUrl}?v=${version}` : ''
  const downloadUrl = baseVideoUrl ? `${baseVideoUrl}?download=true&v=${version}` : ''

  useEffect(() => {
    if (videoRef?.current && src) {
      videoRef.current.load()
    }
  }, [src, videoRef])

  return (
    <section className="animate-float-in overflow-hidden rounded-3xl border border-accent/30 bg-white/[0.05] backdrop-blur-xl">
      <div className="aspect-video bg-black">
        <video key={src} ref={videoRef} id="karaoke-player" src={src} controls autoPlay playsInline className="h-full w-full" />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-widest text-accent">Karaokê pronto 🎉</p>
          <h2 className="truncate text-lg font-semibold">{job.title || 'Seu karaokê'}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2.5">
          {onOpenEditor && (
            <button
              id="edit-subtitles-button"
              type="button"
              onClick={onOpenEditor}
              className="inline-flex items-center gap-2 rounded-xl border border-white/20 bg-white/5 px-4 py-2.5 text-sm font-semibold text-white transition hover:border-accent hover:bg-accent/10 hover:text-accent active:scale-95"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" />
                <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
              </svg>
              Editar Letra e Tempos
            </button>
          )}
          <a
            id="download-button"
            href={downloadUrl}
            download
            className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet to-accent px-5 py-2.5 text-sm font-semibold text-ink transition hover:brightness-110 active:scale-95"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
              <path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            Baixar MP4
          </a>
        </div>
      </div>
    </section>
  )
}

