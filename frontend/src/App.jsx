import { useRef, useState } from 'react'
import { createKaraokeJob, searchSongs } from './api'
import { useJob } from './hooks/useJob'
import SearchBar from './components/SearchBar'
import { ResultCard, ResultSkeleton } from './components/ResultCard'
import PipelinePanel from './components/PipelinePanel'
import VideoPlayer from './components/VideoPlayer'
import SubtitleEditor from './components/SubtitleEditor'

export default function App() {
  const [results, setResults] = useState(null)
  const [searching, setSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)
  const [jobId, setJobId] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [starting, setStarting] = useState(false)
  const [startError, setStartError] = useState(null)
  const [previewId, setPreviewId] = useState(null)
  const [editingSubtitles, setEditingSubtitles] = useState(false)
  const [pollKey, setPollKey] = useState(0)
  const videoRef = useRef(null)

  const { job, connectionError, setJob } = useJob(jobId, pollKey)
  const running = starting || (!!jobId && (!job || !['completed', 'failed'].includes(job.status)))

  const togglePreview = (id) => setPreviewId((cur) => (cur === id ? null : id))

  const handleSearch = async (query) => {
    setPreviewId(null)
    setSearching(true)
    setSearchError(null)
    try {
      setResults(await searchSongs(query))
    } catch (err) {
      setResults(null)
      setSearchError(err.message)
    } finally {
      setSearching(false)
    }
  }

  const handleGenerate = async (song) => {
    setPreviewId(null)
    setStarting(true)
    setStartError(null)
    setSelectedId(song.id)
    setJobId(null)
    try {
      const created = await createKaraokeJob(song.id, song.title, song.uploader)
      setJobId(created.job_id)
    } catch (err) {
      setStartError(err.message)
    } finally {
      setStarting(false)
    }
  }

  const reset = () => {
    setJobId(null)
    setSelectedId(null)
    setStartError(null)
    setEditingSubtitles(false)
  }

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-6xl flex-col gap-10 px-4 py-12 sm:px-6">
      <header className="text-center">
        <p className="mb-3 inline-block rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs font-medium tracking-wide text-white/60">
          IA + FFmpeg • letra sincronizada palavra por palavra
        </p>
        <h1 className="bg-gradient-to-r from-white via-white to-accent bg-clip-text text-4xl font-bold tracking-tight text-transparent sm:text-6xl">
          Karaokê Studio
        </h1>
        <p className="mx-auto mt-4 max-w-xl text-base text-white/55">
          Busque uma música e gere um vídeo de karaokê com instrumental e letra dinâmica.
        </p>
      </header>

      <SearchBar onSearch={handleSearch} loading={searching} />

      {(startError || (jobId && job) || starting) && (
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
          {startError && (
            <p role="alert" className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
              {startError}
            </p>
          )}
          {starting && !job && (
            <p className="text-center text-sm text-white/50">Iniciando pipeline…</p>
          )}
          {job && job.status === 'completed' && (
            <>
              <VideoPlayer
                job={job}
                videoRef={videoRef}
                onOpenEditor={() => setEditingSubtitles((cur) => !cur)}
              />
              {editingSubtitles && (
                <SubtitleEditor
                  job={job}
                  onCancel={() => setEditingSubtitles(false)}
                  onRerenderStarted={(updatedJob) => {
                    setEditingSubtitles(false)
                    setJob(updatedJob)
                    setPollKey((k) => k + 1)
                  }}
                  onSeekVideo={(sec) => {
                    if (videoRef.current) {
                      videoRef.current.currentTime = sec
                      videoRef.current.play()
                    }
                  }}
                />
              )}
            </>
          )}
          {job && job.status !== 'completed' && (
            <PipelinePanel job={job} connectionError={connectionError} />
          )}
          {job && ['completed', 'failed'].includes(job.status) && !editingSubtitles && (
            <button
              id="reset-button"
              onClick={reset}
              className="self-center rounded-xl border border-white/15 px-4 py-2 text-sm text-white/70 transition hover:border-white/40 hover:text-white"
            >
              {job.status === 'completed' ? 'Gerar outro karaokê' : 'Tentar outra música'}
            </button>
          )}
        </div>
      )}

      <main className="flex-1">
        {searchError && (
          <p role="alert" className="mx-auto max-w-xl rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-center text-sm text-red-200">
            {searchError}
          </p>
        )}

        {searching && (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <ResultSkeleton key={i} />
            ))}
          </div>
        )}

        {!searching && results && results.length === 0 && (
          <p className="text-center text-white/50">Nenhum resultado encontrado. Tente outro nome.</p>
        )}

        {!searching && results && results.length > 0 && (
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {results.map((song, i) => (
              <ResultCard
                key={song.id}
                song={song}
                index={i}
                onGenerate={handleGenerate}
                busy={running}
                selected={selectedId === song.id}
                playing={previewId === song.id}
                onTogglePreview={togglePreview}
              />
            ))}
          </div>
        )}
      </main>

      <footer className="text-center text-xs text-white/30">
        Use apenas músicas que você tem direito de utilizar.
      </footer>
    </div>
  )
}
