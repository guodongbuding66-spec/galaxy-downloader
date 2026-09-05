(() => {
  'use strict'

  const state = { status: null, jobs: [], token: sessionStorage.getItem('galaxy.headless.token') || '', view: 'dashboard', refreshTimer: 0, eventController: null }
  const $ = (id) => document.getElementById(id)
  const terminalStates = new Set(['completed', 'failed', 'cancelled'])
  const activeStates = new Set(['preparing', 'downloading', 'merging', 'postprocessing'])

  function headers(extra = {}) {
    const value = { Accept: 'application/json', ...extra }
    if (state.token) value.Authorization = `Bearer ${state.token}`
    return value
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: headers(options.headers || {}), cache: 'no-store' })
    if (response.status === 401) {
      showCredentials(true)
      setConnection(false, 'Authentication required')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function setConnection(online, label) {
    $('connectionDot').classList.toggle('online', online)
    $('connectionDot').classList.toggle('offline', !online)
    $('connectionLabel').textContent = label
  }

  function showCredentials(force) {
    const panel = $('credentialsPanel')
    const shouldShow = force === undefined ? panel.classList.contains('is-hidden') : Boolean(force)
    panel.classList.toggle('is-hidden', !shouldShow)
    if (shouldShow) {
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

  function jobTitle(job) { return job.fileName || job.sourceHost || `Job ${String(job.id || '').slice(0, 8)}` }
  function progressValue(job) { return Math.max(0, Math.min(Number(job.progress) || 0, 100)) }

  function stateBadge(job) {
    const label = String(job.state || 'unknown')
    return `<span class="state" data-state="${escapeHtml(label)}">${escapeHtml(label)}</span>`
  }

  function progress(job) {
    const value = progressValue(job)
    return `<div class="progress-cell"><div class="progress-track" aria-hidden="true"><div class="progress-bar" style="width:${value}%"></div></div><span class="progress-number">${value.toFixed(1)}%</span></div>`
  }

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  }

  function actionButtons(job) {
    const id = escapeHtml(job.id)
    const items = []
    if (['queued', 'preparing', 'downloading'].includes(job.state)) items.push(`<button class="action" data-action="pause" data-id="${id}" type="button">Pause</button>`)
    if (job.state === 'paused') items.push(`<button class="action" data-action="resume" data-id="${id}" type="button">Resume</button>`)
    if (job.state === 'failed') items.push(`<button class="action" data-action="retry" data-id="${id}" type="button">Retry</button>`)
    if (!terminalStates.has(job.state)) items.push(`<button class="action" data-action="cancel" data-id="${id}" type="button">Cancel</button>`)
    return items.join('') || '<span class="muted">—</span>'
  }

  function renderMetrics() {
    const jobs = state.jobs
    const counts = (name) => jobs.filter((job) => job.state === name).length
    $('metricEngine').textContent = state.status ? 'Online' : '—'
    $('metricEngineDetail').textContent = state.status ? (state.status.version || state.status.service || 'Headless API v2') : 'Checking'
    $('metricActive').textContent = jobs.filter((job) => activeStates.has(job.state)).length
    $('metricQueued').textContent = counts('queued')
    $('metricFailed').textContent = counts('failed')
    $('metricCompleted').textContent = counts('completed')
  }

  function renderRecent() {
    const target = $('recentJobs')
    const jobs = state.jobs.slice(0, 8)
    if (!jobs.length) { target.innerHTML = '<div class="empty">No download jobs yet.</div>'; return }
    target.innerHTML = jobs.map((job) => `<div class="recent-row">${stateBadge(job)}<div class="title-cell"><div class="title-primary">${escapeHtml(jobTitle(job))}</div><div class="title-secondary">${escapeHtml(job.sourceHost || '')}</div></div>${progress(job)}<time class="numeric">${escapeHtml(formatDate(job.createdAt))}</time></div>`).join('')
  }

  function renderDownloads() {
    $('downloadCount').textContent = `${state.jobs.length} job${state.jobs.length === 1 ? '' : 's'}`
    const body = $('downloadsBody')
    if (!state.jobs.length) { body.innerHTML = '<tr><td colspan="9"><div class="empty">No downloads. Submit a job through the API or Desktop handoff to see it here.</div></td></tr>'; return }
    body.innerHTML = state.jobs.map((job) => `<tr><td>${stateBadge(job)}</td><td><div class="title-cell"><div class="title-primary">${escapeHtml(jobTitle(job))}</div><div class="title-secondary">${escapeHtml(job.detail || job.id)}</div></div></td><td>${progress(job)}</td><td class="numeric muted">—</td><td class="numeric muted">—</td><td class="numeric muted">—</td><td>${escapeHtml(job.sourceHost || '—')}</td><td class="numeric">${escapeHtml(formatDate(job.createdAt))}</td><td><div class="table-actions">${actionButtons(job)}</div></td></tr>`).join('')
    $('pauseAllButton').disabled = !state.jobs.some((job) => ['queued', 'preparing', 'downloading'].includes(job.state))
    $('resumeAllButton').disabled = !state.jobs.some((job) => job.state === 'paused')
    $('retryFailedButton').disabled = !state.jobs.some((job) => job.state === 'failed')
  }

  function render() { renderMetrics(); renderRecent(); renderDownloads() }

  async function refresh({ quiet = false } = {}) {
    if (!quiet) $('refreshButton').disabled = true
    try {
      const [status, jobs] = await Promise.all([api('/v1/status'), api('/v1/jobs')])
      state.status = status
      state.jobs = Array.isArray(jobs.jobs) ? [...jobs.jobs].sort((a, b) => String(b.createdAt || '').localeCompare(String(a.createdAt || ''))) : []
      render()
      setConnection(true, 'Connected')
      showError('')
      if (!$('credentialsPanel').classList.contains('is-hidden') && state.token) showCredentials(false)
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load Headless API')
      if (!String(error).includes('Bearer token')) setConnection(false, 'Disconnected')
    } finally { $('refreshButton').disabled = false }
  }

  function scheduleRefresh() {
    clearTimeout(state.refreshTimer)
    state.refreshTimer = setTimeout(() => refresh({ quiet: true }), 180)
  }

  async function runAction(id, action) {
    try { await api(`/v1/jobs/${encodeURIComponent(id)}/${action}`, { method: 'POST' }); await refresh({ quiet: true }) }
    catch (error) { showError(error instanceof Error ? error.message : 'Action failed') }
  }

  async function batchAction(action, predicate) {
    const targets = state.jobs.filter(predicate)
    for (const job of targets) {
      try { await api(`/v1/jobs/${encodeURIComponent(job.id)}/${action}`, { method: 'POST' }) }
      catch (error) { showError(error instanceof Error ? error.message : 'Batch action failed'); break }
    }
    await refresh({ quiet: true })
  }

  function switchView(view) {
    state.view = view === 'downloads' ? 'downloads' : 'dashboard'
    $('dashboardView').classList.toggle('is-hidden', state.view !== 'dashboard')
    $('downloadsView').classList.toggle('is-hidden', state.view !== 'downloads')
    $('viewTitle').textContent = state.view === 'downloads' ? 'Downloads' : 'Dashboard'
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.toggle('is-active', button.dataset.view === state.view))
  }

  async function connectEvents() {
    if (state.eventController) state.eventController.abort()
    const controller = new AbortController()
    state.eventController = controller
    try {
      const response = await fetch('/v1/events', { headers: headers(), cache: 'no-store', signal: controller.signal })
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
    } catch (error) {
      if (!controller.signal.aborted) setTimeout(() => connectEvents(), 2500)
      return
    }
    if (!controller.signal.aborted) setTimeout(() => connectEvents(), 500)
  }

  document.addEventListener('click', (event) => {
    const view = event.target.closest('[data-view]')
    if (view) switchView(view.dataset.view)
    const jump = event.target.closest('[data-view-jump]')
    if (jump) switchView(jump.dataset.viewJump)
    const action = event.target.closest('[data-action]')
    if (action) runAction(action.dataset.id, action.dataset.action)
  })
  $('refreshButton').addEventListener('click', () => refresh())
  $('retryButton').addEventListener('click', () => refresh())
  $('credentialsButton').addEventListener('click', () => showCredentials())
  $('credentialsForm').addEventListener('submit', (event) => {
    event.preventDefault()
    state.token = $('tokenInput').value.trim()
    if (state.token) sessionStorage.setItem('galaxy.headless.token', state.token); else sessionStorage.removeItem('galaxy.headless.token')
    showCredentials(false); refresh(); connectEvents()
  })
  $('clearTokenButton').addEventListener('click', () => {
    state.token = ''; sessionStorage.removeItem('galaxy.headless.token'); $('tokenInput').value = ''; refresh(); connectEvents()
  })
  $('pauseAllButton').addEventListener('click', () => batchAction('pause', (job) => ['queued', 'preparing', 'downloading'].includes(job.state)))
  $('resumeAllButton').addEventListener('click', () => batchAction('resume', (job) => job.state === 'paused'))
  $('retryFailedButton').addEventListener('click', () => batchAction('retry', (job) => job.state === 'failed'))

  switchView('dashboard')
  refresh()
  connectEvents()
  setInterval(() => refresh({ quiet: true }), 15000)
})()
