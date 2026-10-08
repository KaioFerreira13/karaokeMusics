import { Spinner } from './SearchBar'

const STEPS = [
  { key: 'download', label: 'Baixando áudio', hint: 'Obtendo a música em alta qualidade' },
  { key: 'separate', label: 'Separando instrumental', hint: 'IA removendo a voz da faixa' },
  { key: 'transcribe', label: 'Alinhando letra', hint: 'Sincronizando cada palavra no tempo' },
  { key: 'render', label: 'Renderizando vídeo', hint: 'Compondo o vídeo final com legendas' },
]

function stepState(index, job) {
  const current = STEPS.findIndex((s) => s.key === job.stage)
  if (job.status === 'completed') return 'done'
  if (job.status === 'failed') {
    if (current === -1) return 'pending'
    return index < current ? 'done' : index === current ? 'failed' : 'pending'
  }
  if (current === -1) return 'pending'
  return index < current ? 'done' : index === current ? 'active' : 'pending'
}

function StepIcon({ state, index }) {
  const base = 'relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border text-sm font-semibold transition-all duration-500'
  if (state === 'done')
    return (
      <span className={`${base} border-accent bg-accent text-ink`}>
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true">
          <path d="m5 12 5 5 9-10" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </span>
    )
  if (state === 'failed')
    return (
      <span className={`${base} border-red-400 bg-red-500/20 text-red-300`}>
        <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="3" aria-hidden="true">
          <path d="m6 6 12 12M18 6 6 18" strokeLinecap="round" />
        </svg>
      </span>
    )
  if (state === 'active')
    return (
      <span className={`${base} border-accent/60 bg-accent/10 text-accent`}>
        <span className="absolute inset-0 animate-ping rounded-full bg-accent/20" />
        <Spinner className="relative h-5 w-5" />
      </span>
    )
  return <span className={`${base} border-white/15 bg-white/5 text-white/40`}>{index + 1}</span>
}

export default function PipelinePanel({ job, connectionError }) {
  const failed = job.status === 'failed'
  const done = job.status === 'completed'
  const queued = !job.stage && !failed && !done
  const pct = Math.round(job.progress)

  return (
    <section
      aria-live="polite"
      className="animate-float-in rounded-3xl border border-white/10 bg-white/[0.05] p-6 backdrop-blur-xl sm:p-8"
    >
      <header className="mb-6 flex flex-wrap items-end justify-between gap-2">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-widest text-white/40">
            {failed ? 'Falhou' : done ? 'Concluído' : 'Processando'}
          </p>
          <h2 className="truncate text-lg font-semibold">{job.title || 'Seu karaokê'}</h2>
        </div>
        <span className="text-3xl font-semibold tabular-nums text-accent">{pct}%</span>
      </header>

      <div
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        className="mb-8 h-2 overflow-hidden rounded-full bg-white/10"
      >
        <div
          style={{ width: `${Math.max(pct, queued ? 3 : 2)}%` }}
          className={`h-full rounded-full transition-all duration-700 ${
            failed
              ? 'bg-red-400'
              : 'animate-shimmer bg-[linear-gradient(90deg,var(--color-violet),var(--color-accent),var(--color-violet))] bg-[length:200%_100%]'
          }`}
        />
      </div>

      <ol className="grid gap-4 sm:grid-cols-4">
        {STEPS.map((step, i) => {
          const state = stepState(i, job)
          return (
            <li key={step.key} className="flex items-start gap-3 sm:flex-col">
              <StepIcon state={state} index={i} />
              <div>
                <p
                  className={`text-sm font-semibold transition-colors ${
                    state === 'pending' ? 'text-white/40' : state === 'failed' ? 'text-red-300' : 'text-white'
                  }`}
                >
                  {step.label}
                </p>
                <p className="mt-0.5 text-xs text-white/40">
                  {state === 'active' && step.key === 'render' && job.stage_progress > 0
                    ? `${Math.round(job.stage_progress)}% renderizado`
                    : state === 'active'
                      ? step.hint
                      : state === 'done'
                        ? 'Concluído'
                        : state === 'failed'
                          ? 'Erro nesta etapa'
                          : 'Aguardando'}
                </p>
              </div>
            </li>
          )
        })}
      </ol>

      {queued && <p className="mt-6 text-sm text-white/50">Na fila — iniciando em instantes…</p>}
      {!done && !failed && (
        <p className="mt-6 text-xs text-white/35">
          Isso pode levar alguns minutos, principalmente nas etapas de IA. Pode manter esta aba aberta.
        </p>
      )}
      {connectionError && !failed && (
        <p className="mt-4 rounded-lg bg-amber-500/10 px-3 py-2 text-xs text-amber-300">
          Conexão instável: {connectionError} Tentando novamente…
        </p>
      )}
      {failed && (
        <p role="alert" className="mt-6 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {job.error_message || 'Algo deu errado ao gerar o karaokê.'}
        </p>
      )}
    </section>
  )
}
