export default function VideoPlayer({ job }) {
  const src = job.video_url
  return (
    <section className="animate-float-in overflow-hidden rounded-3xl border border-accent/30 bg-white/[0.05] backdrop-blur-xl">
      <div className="aspect-video bg-black">
        <video id="karaoke-player" src={src} controls autoPlay playsInline className="h-full w-full" />
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 p-5">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-widest text-accent">Karaokê pronto 🎉</p>
          <h2 className="truncate text-lg font-semibold">{job.title || 'Seu karaokê'}</h2>
        </div>
        <a
          id="download-button"
          href={`${src}?download=true`}
          download
          className="inline-flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet to-accent px-5 py-2.5 text-sm font-semibold text-ink transition hover:brightness-110 active:scale-95"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.5" aria-hidden="true">
            <path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Baixar MP4
        </a>
      </div>
    </section>
  )
}
