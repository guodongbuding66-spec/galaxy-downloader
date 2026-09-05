(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const state = {
    status: null,
    jobs: [],
    token: sessionStorage.getItem('galaxy.headless.token') || '',
    view: 'dashboard',
    sortKey: 'createdAt',
    sortDirection: 'desc',
    refreshTimer: 0,
    eventController: null,
    mediaSummary: null,
    mediaItems: [],
    mediaLimit: 50,
    mediaOffset: 0,
    mediaQuery: '',
    mediaType: '',
    transcriptMediaItems: [],
    selectedMediaId: '',
    transcriptRows: [],
  }

  const terminal = new Set(['completed', 'failed', 'cancelled'])
  const active = new Set(['preparing', 'downloading', 'merging', 'postprocessing'])
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const jobTitle = (job) => job.fileName || job.sourceHost || `Job ${String(job.id || '').slice(0, 8)}`
  const progressValue = (job) => Math.max(0, Math.min(Number(job.progress) || 0, 100))

  function requestHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    if (state.token) headers.Authorization = `Bearer ${state.token}`
    return headers
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: requestHeaders(options.headers || {}), cache: 'no-store' })
    if (response.status === 401) {
      showCredentials(true)
      setConnection(false, 'Authentication required')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function postJson(path, payload = {}) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  }

  function setConnection(ok, label) {
    $('connectionDot').classList.toggle('online', ok)
    $('connectionDot').classList.toggle('offline', !ok)
    $('connectionLabel').textContent = label
  }

  function showCredentials(force) {
    const panel = $('credentialsPanel')
    const show = force === undefined ? panel.classList.contains('is-hidden') : Boolean(force)
    panel.classList.toggle('is-hidden', !show)
    if (show) {
      $('tokenInput').value = state.token
      $('tokenInput').focus()
    }
  }

  function showError(message) {
    $('errorText').textContent = message || ''
    $('errorNotice').classList.toggle('is-hidden', !message)
  }

  function formatDate(value) {
    if (!value) return '—'
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
  }

  function formatDuration(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0))
    if (!total) return '—'
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = total % 60
    return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`
  }

  function formatTimestamp(value) {
    const total = Math.max(0, Number(value) || 0)
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = Math.floor(total % 60)
    const millis = Math.floor((total - Math.floor(total)) * 1000)
    const base = hours ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}` : `${minutes}:${String(seconds).padStart(2, '0')}`
    return millis ? `${base}.${String(millis).padStart(3, '0')}` : base
  }

  function formatBytes(value) {
    let bytes = Math.max(0, Number(value) || 0)
    if (!bytes) return '—'
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let unit = 0
    while (bytes >= 1024 && unit < units.length - 1) { bytes /= 1024; unit += 1 }
    return `${bytes >= 10 || unit === 0 ? bytes.toFixed(0) : bytes.toFixed(1)} ${units[unit]}`
  }

  function badge(job) {
    const value = String(job.state || 'unknown')
    return `<span class="state" data-state="${esc(value)}">${esc(value)}</span>`
  }

  function progress(job) {
    const value = progressValue(job)
    return `<div class="progress-cell"><div class="progress-track" aria-hidden="true"><div class="progress-bar" style="width:${value}%"></div></div><span class="progress-number">${value.toFixed(1)}%</span></div>`
  }

  function jobActions(job) {
    const id = esc(job.id)
    const actions = []
    if (['queued', 'preparing', 'downloading'].includes(job.state)) actions.push(`<button class="action" data-action="pause" data-id="${id}" type="button">Pause</button>`)
    if (job.state === 'paused') actions.push(`<button class="action" data-action="resume" data-id="${id}" type="button">Resume</button>`)
    if (job.state === 'failed') actions.push(`<button class="action" data-action="retry" data-id="${id}" type="button">Retry</button>`)
    if (!terminal.has(job.state)) actions.push(`<button class="action" data-action="cancel" data-id="${id}" type="button">Cancel</button>`)
    return actions.join('') || '<span class="muted">—</span>'
  }

  function sortedJobs() {
    const key = state.sortKey
    const value = (job) => key === 'title' ? jobTitle(job).toLowerCase() : key === 'progress' ? progressValue(job) : key === 'createdAt' ? Date.parse(job.createdAt || '') || 0 : String(job[key] || '').toLowerCase()
    return [...state.jobs].sort((a, b) => {
      const av = value(a), bv = value(b)
      const order = typeof av === 'number' ? av - bv : String(av).localeCompare(String(bv))
      return state.sortDirection === 'asc' ? order : -order
    })
  }

  function renderDownloadSort() {
    document.querySelectorAll('[data-sort-header]').forEach((header) => header.removeAttribute('aria-sort'))
    document.querySelectorAll('[data-sort]').forEach((button) => {
      const selected = button.dataset.sort === state.sortKey
      button.dataset.direction = selected ? state.sortDirection : ''
      if (selected) button.closest('th').setAttribute('aria-sort', state.sortDirection === 'asc' ? 'ascending' : 'descending')
    })
  }

  function renderMetrics() {
    const count = (name) => state.jobs.filter((job) => job.state === name).length
    $('metricEngine').textContent = state.status ? 'Online' : '—'
    $('metricEngineDetail').textContent = state.status ? (state.status.version || state.status.service || 'Headless API v2') : 'Checking'
    $('metricActive').textContent = state.jobs.filter((job) => active.has(job.state)).length
    $('metricQueued').textContent = count('queued')
    $('metricFailed').textContent = count('failed')
    $('metricCompleted').textContent = count('completed')
  }

  function renderRecent() {
    const jobs = [...state.jobs].sort((a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || ''))).slice(0, 8)
    $('recentJobs').innerHTML = jobs.length ? jobs.map((job) => `<div class="recent-row">${badge(job)}<div class="title-cell"><div class="title-primary">${esc(jobTitle(job))}</div><div class="title-secondary">${esc(job.sourceHost || '')}</div></div>${progress(job)}<time class="numeric">${esc(formatDate(job.createdAt))}</time></div>`).join('') : '<div class="empty">No download jobs yet.</div>'
  }

  function renderDownloads() {
    $('downloadCount').textContent = `${state.jobs.length} job${state.jobs.length === 1 ? '' : 's'}`
    const jobs = sortedJobs()
    $('downloadsBody').innerHTML = jobs.length ? jobs.map((job) => `<tr><td>${badge(job)}</td><td><div class="title-cell"><div class="title-primary">${esc(jobTitle(job))}</div><div class="title-secondary">${esc(job.detail || job.id)}</div></div></td><td>${progress(job)}</td><td class="numeric muted">—</td><td class="numeric muted">—</td><td class="numeric muted">—</td><td>${esc(job.sourceHost || '—')}</td><td class="numeric">${esc(formatDate(job.createdAt))}</td><td><div class="table-actions">${jobActions(job)}</div></td></tr>`).join('') : '<tr><td colspan="9"><div class="empty">No downloads. Submit a job through the API or Desktop handoff to see it here.</div></td></tr>'
    $('pauseAllButton').disabled = !state.jobs.some((job) => ['queued', 'preparing', 'downloading'].includes(job.state))
    $('resumeAllButton').disabled = !state.jobs.some((job) => job.state === 'paused')
    $('retryFailedButton').disabled = !state.jobs.some((job) => job.state === 'failed')
    renderDownloadSort()
  }

  function renderCore() {
    renderMetrics()
    renderRecent()
    renderDownloads()
  }

  async function refreshCore({ quiet = false } = {}) {
    if (!quiet) $('refreshButton').disabled = true
    try {
      const [status, jobs] = await Promise.all([api('/v1/status'), api('/v1/jobs')])
      state.status = status
      state.jobs = Array.isArray(jobs.jobs) ? jobs.jobs : []
      renderCore()
      setConnection(true, 'Connected')
      showError('')
      if (!$('credentialsPanel').classList.contains('is-hidden') && state.token) showCredentials(false)
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load Headless API')
      if (!String(error).includes('Bearer token')) setConnection(false, 'Disconnected')
    } finally {
      $('refreshButton').disabled = false
    }
  }

  function renderLibrarySummary() {
    const summary = state.mediaSummary || {}
    $('libraryTotal').textContent = Number(summary.total) || 0
    $('libraryAvailable').textContent = Number(summary.available) || 0
    $('libraryMissing').textContent = Number(summary.missing) || 0
    $('libraryVideo').textContent = Number(summary.video) || 0
    $('libraryAudio').textContent = Number(summary.audio) || 0
  }

  function renderLibrary() {
    renderLibrarySummary()
    $('libraryCount').textContent = `${state.mediaItems.length} item${state.mediaItems.length === 1 ? '' : 's'} on this page`
    $('libraryPageLabel').textContent = `Page ${Math.floor(state.mediaOffset / state.mediaLimit) + 1}`
    $('libraryPrevButton').disabled = state.mediaOffset === 0
    $('libraryNextButton').disabled = state.mediaItems.length < state.mediaLimit
    $('libraryBody').innerHTML = state.mediaItems.length ? state.mediaItems.map((item) => `<tr><td><div class="title-cell"><div class="title-primary">${esc(item.title || item.fileName)}</div><div class="title-secondary">${esc(item.fileName || item.id)}</div></div></td><td><span class="media-type">${esc(item.mediaType || 'other')}</span></td><td class="numeric">${esc(formatDuration(item.durationSeconds))}</td><td class="numeric">${esc(formatBytes(item.sizeBytes))}</td><td>${esc(item.sourceHost || '—')}</td><td class="numeric">${esc(formatDate(item.finishedAt))}</td><td><span class="availability ${item.available ? 'available' : 'missing'}">${item.available ? 'Available' : 'Missing'}</span></td><td><button class="action" data-media-transcript="${esc(item.id)}" type="button">Transcript</button></td></tr>`).join('') : '<tr><td colspan="8"><div class="empty">No media items match this filter.</div></td></tr>'
  }

  async function loadLibrary({ preserveOffset = true } = {}) {
    if (!preserveOffset) state.mediaOffset = 0
    $('libraryBody').innerHTML = '<tr><td colspan="8"><div class="empty">Loading Library…</div></td></tr>'
    const params = new URLSearchParams({ limit: String(state.mediaLimit), offset: String(state.mediaOffset) })
    if (state.mediaQuery) params.set('q', state.mediaQuery)
    if (state.mediaType) params.set('type', state.mediaType)
    try {
      const [summary, items] = await Promise.all([api('/v1/media/summary'), api(`/v1/media?${params}`)])
      state.mediaSummary = summary.summary || {}
      state.mediaItems = Array.isArray(items.items) ? items.items : []
      renderLibrary()
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load Library')
      $('libraryBody').innerHTML = '<tr><td colspan="8"><div class="empty">Library is unavailable.</div></td></tr>'
    }
  }

  async function syncLibrary() {
    $('librarySyncButton').disabled = true
    try {
      const result = await postJson('/v1/media/sync')
      state.mediaSummary = result.summary || state.mediaSummary
      await loadLibrary({ preserveOffset: false })
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Library sync failed')
    } finally {
      $('librarySyncButton').disabled = false
    }
  }

  function mediaTitle(mediaId) {
    const item = [...state.transcriptMediaItems, ...state.mediaItems].find((media) => media.id === mediaId)
    return item ? (item.title || item.fileName || mediaId) : mediaId
  }

  function renderTranscriptMediaList() {
    $('transcriptMediaCount').textContent = String(state.transcriptMediaItems.length)
    $('transcriptMediaList').innerHTML = state.transcriptMediaItems.length ? state.transcriptMediaItems.map((item) => `<button class="media-list-item ${item.id === state.selectedMediaId ? 'is-selected' : ''}" data-transcript-media="${esc(item.id)}" type="button"><strong>${esc(item.title || item.fileName)}</strong><span>${esc(item.mediaType || 'other')} · ${esc(formatDuration(item.durationSeconds))}</span></button>`).join('') : '<div class="empty small-empty">No media items available.</div>'
  }

  async function loadTranscriptMedia() {
    try {
      const result = await api('/v1/media?limit=100&offset=0')
      state.transcriptMediaItems = Array.isArray(result.items) ? result.items : []
      renderTranscriptMediaList()
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load transcript media list')
    }
  }

  function transcriptRowMarkup(row) {
    const mediaId = row.mediaId || state.selectedMediaId
    const mediaLabel = row.mediaId && !state.selectedMediaId ? `<span class="segment-media">${esc(mediaTitle(mediaId))}</span>` : ''
    const speaker = row.speaker ? `<button class="speaker-chip" data-speaker-fill="${esc(row.speaker)}" type="button">${esc(row.speaker)}</button>` : '<span class="muted">No speaker</span>'
    return `<article class="segment"><div class="segment-time"><button class="time-button" type="button" disabled title="Web Dashboard has no media streaming endpoint yet">${esc(formatTimestamp(row.startSeconds))}</button><span>→ ${esc(formatTimestamp(row.endSeconds))}</span></div><div class="segment-body"><div class="segment-meta">${speaker}${mediaLabel}</div><p>${esc(row.text || '')}</p></div></article>`
  }

  function renderTranscriptRows(message = '') {
    $('transcriptResults').innerHTML = state.transcriptRows.length ? state.transcriptRows.map(transcriptRowMarkup).join('') : `<div class="empty">${esc(message || 'No transcript segments found.')}</div>`
  }

  function updateTranscriptSelection() {
    const selected = state.selectedMediaId
    $('transcriptIndexButton').disabled = !selected
    $('transcriptExportButton').disabled = !selected
    $('speakerRelabelButton').disabled = !selected
    $('transcriptTitle').textContent = selected ? mediaTitle(selected) : 'Transcript'
    $('transcriptMeta').textContent = selected ? 'Indexed transcript segments for this Library item.' : 'Search all indexed transcripts or select a Library item.'
    renderTranscriptMediaList()
  }

  async function selectTranscriptMedia(mediaId) {
    state.selectedMediaId = String(mediaId || '')
    updateTranscriptSelection()
    if (!state.selectedMediaId) {
      state.transcriptRows = []
      renderTranscriptRows('Select a media item or run a global transcript search.')
      return
    }
    $('transcriptResults').innerHTML = '<div class="empty">Loading transcript…</div>'
    try {
      const result = await api(`/v1/transcripts/${encodeURIComponent(state.selectedMediaId)}?limit=5000`)
      state.transcriptRows = Array.isArray(result.segments) ? result.segments : []
      renderTranscriptRows('No indexed segments. Use Index Transcript if a subtitle transcript exists for this media item.')
      showError('')
    } catch (error) {
      state.transcriptRows = []
      renderTranscriptRows('Transcript is unavailable for this item.')
      showError(error instanceof Error ? error.message : 'Unable to load transcript')
    }
  }

  async function searchTranscript() {
    const query = $('transcriptSearch').value.trim()
    const speaker = $('transcriptSpeaker').value.trim()
    const params = new URLSearchParams({ limit: '500' })
    if (query) params.set('q', query)
    if (speaker) params.set('speaker', speaker)
    if (state.selectedMediaId) params.set('mediaId', state.selectedMediaId)
    $('transcriptResults').innerHTML = '<div class="empty">Searching transcripts…</div>'
    try {
      const result = await api(`/v1/transcripts/search?${params}`)
      state.transcriptRows = Array.isArray(result.results) ? result.results : []
      renderTranscriptRows('No matching transcript segments.')
      $('transcriptMeta').textContent = `${state.transcriptRows.length} result${state.transcriptRows.length === 1 ? '' : 's'}${state.selectedMediaId ? ` in ${mediaTitle(state.selectedMediaId)}` : ' across indexed transcripts'}.`
      showError('')
    } catch (error) {
      state.transcriptRows = []
      renderTranscriptRows('Transcript search failed.')
      showError(error instanceof Error ? error.message : 'Transcript search failed')
    }
  }

  async function indexTranscript() {
    if (!state.selectedMediaId) return
    $('transcriptIndexButton').disabled = true
    try {
      const result = await postJson(`/v1/transcripts/${encodeURIComponent(state.selectedMediaId)}/index`)
      $('transcriptMeta').textContent = `Indexed ${Number(result.segmentCount) || 0} segment${Number(result.segmentCount) === 1 ? '' : 's'}.`
      await selectTranscriptMedia(state.selectedMediaId)
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Transcript indexing failed')
    } finally {
      $('transcriptIndexButton').disabled = !state.selectedMediaId
    }
  }

  async function exportTranscript() {
    if (!state.selectedMediaId) return
    $('transcriptExportButton').disabled = true
    try {
      const format = $('transcriptExportFormat').value
      const result = await postJson(`/v1/transcripts/${encodeURIComponent(state.selectedMediaId)}/export`, { format, basename: mediaTitle(state.selectedMediaId), includeSpeaker: true })
      const exported = result.export || {}
      $('transcriptMeta').textContent = `Exported ${exported.fileName || format} · ${Number(exported.segmentCount) || 0} segments · ${formatBytes(exported.sizeBytes)}`
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Transcript export failed')
    } finally {
      $('transcriptExportButton').disabled = !state.selectedMediaId
    }
  }

  async function relabelSpeaker() {
    if (!state.selectedMediaId) return
    const oldLabel = $('oldSpeaker').value.trim()
    const newLabel = $('newSpeaker').value.trim()
    if (!oldLabel || !newLabel) {
      showError('Old speaker and new speaker are required')
      return
    }
    $('speakerRelabelButton').disabled = true
    try {
      const result = await postJson(`/v1/transcripts/${encodeURIComponent(state.selectedMediaId)}/speakers/relabel`, { oldLabel, newLabel })
      $('oldSpeaker').value = ''
      $('newSpeaker').value = ''
      $('transcriptMeta').textContent = `Relabeled ${Number(result.updated) || 0} segment${Number(result.updated) === 1 ? '' : 's'} from ${oldLabel} to ${newLabel}.`
      await selectTranscriptMedia(state.selectedMediaId)
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Speaker relabel failed')
    } finally {
      $('speakerRelabelButton').disabled = !state.selectedMediaId
    }
  }

  async function refreshCurrent() {
    await refreshCore()
    if (state.view === 'library') await loadLibrary()
    if (state.view === 'transcript') {
      await loadTranscriptMedia()
      if (state.selectedMediaId) await selectTranscriptMedia(state.selectedMediaId)
    }
  }

  function scheduleRefresh() {
    clearTimeout(state.refreshTimer)
    state.refreshTimer = setTimeout(() => refreshCore({ quiet: true }), 180)
  }

  async function runJobAction(id, action) {
    try {
      await api(`/v1/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST' })
      await refreshCore({ quiet: true })
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Action failed')
    }
  }

  async function batchJobAction(action, predicate) {
    for (const job of state.jobs.filter(predicate)) {
      try { await api(`/v1/jobs/${encodeURIComponent(job.id)}/${action}`, { method: 'POST' }) }
      catch (error) { showError(error instanceof Error ? error.message : 'Batch action failed'); break }
    }
    await refreshCore({ quiet: true })
  }

  function switchView(view) {
    const allowed = new Set(['dashboard', 'downloads', 'library', 'transcript'])
    state.view = allowed.has(view) ? view : 'dashboard'
    const titles = { dashboard: 'Dashboard', downloads: 'Downloads', library: 'Library', transcript: 'Transcript' }
    for (const name of allowed) $(`${name}View`).classList.toggle('is-hidden', state.view !== name)
    $('viewTitle').textContent = titles[state.view]
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button.dataset.view === state.view))
    if (state.view === 'library') loadLibrary()
    if (state.view === 'transcript') {
      loadTranscriptMedia().then(() => {
        updateTranscriptSelection()
        if (state.selectedMediaId) selectTranscriptMedia(state.selectedMediaId)
      })
    }
  }

  async function connectEvents() {
    if (state.eventController) state.eventController.abort()
    const controller = new AbortController()
    state.eventController = controller
    try {
      const response = await fetch('/v1/events', { headers: requestHeaders(), cache: 'no-store', signal: controller.signal })
      if (response.status === 401) { showCredentials(true); return }
      if (!response.ok || !response.body) throw new Error(`Events unavailable (${response.status})`)
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      while (!controller.signal.aborted) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() || ''
        if (frames.some((frame) => frame.split('\n').some((line) => line.startsWith('data:')))) scheduleRefresh()
      }
    } catch {
      if (!controller.signal.aborted) setTimeout(connectEvents, 2500)
      return
    }
    if (!controller.signal.aborted) setTimeout(connectEvents, 500)
  }

  document.addEventListener('click', (event) => {
    const view = event.target.closest('[data-view]')
    if (view) switchView(view.dataset.view)
    const jump = event.target.closest('[data-view-jump]')
    if (jump) switchView(jump.dataset.viewJump)
    const action = event.target.closest('[data-action]')
    if (action) runJobAction(action.dataset.id, action.dataset.action)
    const sort = event.target.closest('[data-sort]')
    if (sort) {
      const key = sort.dataset.sort
      state.sortDirection = state.sortKey === key && state.sortDirection === 'asc' ? 'desc' : 'asc'
      state.sortKey = key
      renderDownloads()
    }
    const mediaTranscript = event.target.closest('[data-media-transcript]')
    if (mediaTranscript) {
      state.selectedMediaId = mediaTranscript.dataset.mediaTranscript
      switchView('transcript')
    }
    const transcriptMedia = event.target.closest('[data-transcript-media]')
    if (transcriptMedia) selectTranscriptMedia(transcriptMedia.dataset.transcriptMedia)
    const speakerFill = event.target.closest('[data-speaker-fill]')
    if (speakerFill) {
      $('oldSpeaker').value = speakerFill.dataset.speakerFill
      $('newSpeaker').focus()
    }
  })

  $('refreshButton').addEventListener('click', refreshCurrent)
  $('retryButton').addEventListener('click', refreshCurrent)
  $('credentialsButton').addEventListener('click', () => showCredentials())
  $('credentialsForm').addEventListener('submit', (event) => {
    event.preventDefault()
    state.token = $('tokenInput').value.trim()
    if (state.token) sessionStorage.setItem('galaxy.headless.token', state.token)
    else sessionStorage.removeItem('galaxy.headless.token')
    showCredentials(false)
    refreshCurrent()
    connectEvents()
  })
  $('clearTokenButton').addEventListener('click', () => {
    state.token = ''
    sessionStorage.removeItem('galaxy.headless.token')
    $('tokenInput').value = ''
    refreshCurrent()
    connectEvents()
  })

  $('pauseAllButton').addEventListener('click', () => batchJobAction('pause', (job) => ['queued', 'preparing', 'downloading'].includes(job.state)))
  $('resumeAllButton').addEventListener('click', () => batchJobAction('resume', (job) => job.state === 'paused'))
  $('retryFailedButton').addEventListener('click', () => batchJobAction('retry', (job) => job.state === 'failed'))

  $('libraryFilterForm').addEventListener('submit', (event) => {
    event.preventDefault()
    state.mediaQuery = $('librarySearch').value.trim()
    state.mediaType = $('libraryType').value
    loadLibrary({ preserveOffset: false })
  })
  $('libraryResetButton').addEventListener('click', () => {
    $('librarySearch').value = ''
    $('libraryType').value = ''
    state.mediaQuery = ''
    state.mediaType = ''
    loadLibrary({ preserveOffset: false })
  })
  $('librarySyncButton').addEventListener('click', syncLibrary)
  $('libraryPrevButton').addEventListener('click', () => { state.mediaOffset = Math.max(0, state.mediaOffset - state.mediaLimit); loadLibrary() })
  $('libraryNextButton').addEventListener('click', () => { state.mediaOffset += state.mediaLimit; loadLibrary() })

  $('transcriptSearchForm').addEventListener('submit', (event) => { event.preventDefault(); searchTranscript() })
  $('transcriptClearButton').addEventListener('click', () => {
    $('transcriptSearch').value = ''
    $('transcriptSpeaker').value = ''
    if (state.selectedMediaId) selectTranscriptMedia(state.selectedMediaId)
    else { state.transcriptRows = []; $('transcriptMeta').textContent = 'Search all indexed transcripts or select a Library item.'; renderTranscriptRows('Select a media item or run a global transcript search.') }
  })
  $('transcriptIndexButton').addEventListener('click', indexTranscript)
  $('transcriptExportButton').addEventListener('click', exportTranscript)
  $('speakerRelabelForm').addEventListener('submit', (event) => { event.preventDefault(); relabelSpeaker() })

  switchView('dashboard')
  refreshCore()
  connectEvents()
  setInterval(() => refreshCore({ quiet: true }), 15000)
})()
