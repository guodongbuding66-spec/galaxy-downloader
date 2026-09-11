(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const state = {
    engine: null,
    tool: null,
    jobs: [],
    lastToolResult: null,
    toolActionPending: false,
    submitPending: false,
    pollTimer: null,
  }

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  }

  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: authHeaders(options.headers || {}),
      cache: 'no-store',
    })
    if (response.status === 401) {
      $('credentialsPanel')?.classList.remove('is-hidden')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function postJson(path, payload) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }

  function showError(message) {
    if (!$('errorNotice')) return
    $('errorText').textContent = message || ''
    $('errorNotice').classList.toggle('is-hidden', !message)
  }

  function injectShell() {
    const nav = document.querySelector('.sidebar nav')
    const main = document.querySelector('.main')
    if (!nav || !main || $('galleryDlView')) return

    const button = document.createElement('button')
    button.className = 'nav-item'
    button.type = 'button'
    button.dataset.galleryView = 'gallery-dl'
    button.textContent = 'Gallery'
    const settingsButton = nav.querySelector('[data-settings-view]')
    nav.insertBefore(button, settingsButton || null)

    const section = document.createElement('section')
    section.id = 'galleryDlView'
    section.className = 'view is-hidden gallery-view'
    section.innerHTML = `
      <div class="metrics" aria-label="gallery-dl summary">
        <article class="metric"><span>Tool</span><strong id="galleryMetricTool">—</strong><small id="galleryMetricToolDetail">managed gallery-dl</small></article>
        <article class="metric"><span>Version</span><strong id="galleryMetricVersion">—</strong><small>verified managed package</small></article>
        <article class="metric"><span>Active</span><strong id="galleryMetricActive">0</strong><small>currently downloading</small></article>
        <article class="metric"><span>Queued</span><strong id="galleryMetricQueued">0</strong><small>waiting tasks</small></article>
        <article class="metric"><span>Saved</span><strong id="galleryMetricCompleted">0</strong><small>completed tasks</small></article>
      </div>

      <div class="gallery-grid">
        <section class="panel gallery-submit-panel">
          <div class="panel-header">
            <div><h2>Gallery download</h2><p>Download image galleries from a public HTTP(S) URL through the managed gallery-dl runtime.</p></div>
            <button class="button secondary" id="galleryRefreshButton" type="button">Refresh</button>
          </div>
          <form id="gallerySubmitForm" class="gallery-form">
            <label class="field grow" for="gallerySourceUrl"><span>Source URL</span><input id="gallerySourceUrl" name="sourceUrl" type="url" required autocomplete="off" inputmode="url" placeholder="https://example.com/gallery"></label>
            <label class="field gallery-limit-field" for="galleryMaxFiles"><span>Max files</span><input id="galleryMaxFiles" name="maxFiles" type="number" min="1" max="500" step="1" value="500" required></label>
            <label class="field gallery-rate-field" for="galleryRateLimit"><span>Rate <small>MiB/s · Optional</small></span><input id="galleryRateLimit" name="rateLimitMiB" type="number" min="0.1" max="1024" step="0.1" inputmode="decimal" placeholder="Unlimited" aria-describedby="galleryRateHelp" disabled><small id="galleryRateHelp">Blank keeps gallery-dl unlimited.</small></label>
            <label class="gallery-archive-option" for="galleryArchiveEnabled">
              <input id="galleryArchiveEnabled" name="archiveEnabled" type="checkbox" aria-describedby="galleryArchiveHelp" disabled>
              <span><strong>Archive</strong><small id="galleryArchiveHelp">Skip files already recorded by this Local Engine.</small></span>
            </label>
            <label class="gallery-resume-option" for="galleryResumeEnabled">
              <input id="galleryResumeEnabled" name="resumeEnabled" type="checkbox" aria-describedby="galleryResumeHelp" disabled>
              <span><strong>Resume</strong><small id="galleryResumeHelp">Reuse this task's managed directory on Retry so gallery-dl can reuse completed and .part files.</small></span>
            </label>
            <button class="button primary gallery-submit-button" id="gallerySubmitButton" type="submit">Add download</button>
            <fieldset class="gallery-date-range" id="galleryDateRange" disabled>
              <legend>Date filter <span>Optional</span></legend>
              <div class="gallery-date-controls">
                <label class="field gallery-date-field" for="galleryDateAfter"><span>After</span><input id="galleryDateAfter" name="dateAfter" type="date" aria-describedby="galleryDateHelp"></label>
                <span class="gallery-date-divider" aria-hidden="true">to</span>
                <label class="field gallery-date-field" for="galleryDateBefore"><span>Before</span><input id="galleryDateBefore" name="dateBefore" type="date" aria-describedby="galleryDateHelp"></label>
              </div>
              <small id="galleryDateHelp">Uses gallery-dl native post ordering. Some sites with pinned older posts can stop an “After” scan earlier than expected.</small>
            </fieldset>
          </form>
          <div class="gallery-guidance" id="gallerySubmitStatus" role="status">Only the URL, file-count limit, optional Date values, optional numeric Rate, Archive boolean and explicit Resume opt-in are sent. Blank Rate means unlimited; raw gallery-dl rate strings and paths are never exposed.</div>
        </section>

        <section class="panel gallery-tool-panel">
          <div class="panel-header"><div><h2>Managed tool</h2><p id="galleryToolSummary">Checking local gallery-dl status…</p></div></div>
          <dl class="gallery-tool-facts">
            <div><dt>Install state</dt><dd id="galleryToolInstalled">—</dd></div>
            <div><dt>Current version</dt><dd id="galleryToolVersion">—</dd></div>
            <div><dt>Available version</dt><dd id="galleryToolAvailable">—</dd></div>
            <div><dt>Mutation state</dt><dd id="galleryToolMutation">—</dd></div>
          </dl>
          <div class="gallery-tool-actions">
            <button class="button secondary" id="galleryToolCheck" type="button">Check update</button>
            <button class="button primary" id="galleryToolInstall" type="button">Install</button>
            <button class="button primary" id="galleryToolUpdate" type="button">Update</button>
            <button class="button secondary gallery-danger" id="galleryToolRemove" type="button">Remove</button>
          </div>
          <div class="gallery-tool-message" id="galleryToolMessage" role="status">Tool checks are explicit; startup never contacts the provider.</div>
        </section>
      </div>

      <section class="panel section-gap gallery-jobs-panel">
        <div class="panel-header"><div><h2>Gallery tasks</h2><p id="galleryJobsMeta">Recent managed gallery-dl tasks.</p></div></div>
        <div id="galleryJobsList" class="gallery-jobs-list"><div class="empty">Open Gallery to load tasks.</div></div>
      </section>`
    main.appendChild(section)
  }

  function hideOtherViews() {
    document.querySelectorAll('.main > .view').forEach((view) => view.classList.add('is-hidden'))
    document.querySelectorAll('.sidebar .nav-item').forEach((button) => button.classList.remove('is-active'))
  }

  function isVisible() {
    return Boolean($('galleryDlView') && !$('galleryDlView').classList.contains('is-hidden'))
  }

  function stopPolling() {
    if (state.pollTimer !== null) {
      window.clearTimeout(state.pollTimer)
      state.pollTimer = null
    }
  }

  function hasLiveJobs() {
    return state.jobs.some((job) => job.state === 'queued' || job.state === 'active')
  }

  function schedulePolling() {
    stopPolling()
    if (!isVisible() || !hasLiveJobs()) return
    state.pollTimer = window.setTimeout(async () => {
      state.pollTimer = null
      if (!isVisible()) return
      try {
        await loadJobs()
      } catch (error) {
        showError(error instanceof Error ? error.message : 'Unable to refresh gallery tasks')
      }
    }, 3000)
  }

  function showGallery() {
    hideOtherViews()
    $('galleryDlView').classList.remove('is-hidden')
    document.querySelector('[data-gallery-view="gallery-dl"]')?.classList.add('is-active')
    $('viewTitle').textContent = 'Gallery'
    loadGallery()
  }

  function hideGallery() {
    $('galleryDlView')?.classList.add('is-hidden')
    document.querySelector('[data-gallery-view="gallery-dl"]')?.classList.remove('is-active')
    stopPolling()
  }

  function setText(id, value) {
    const element = $(id)
    if (element) element.textContent = String(value ?? '—')
  }

  function stateLabel(value) {
    const labels = {
      queued: 'Queued',
      active: 'Active',
      completed: 'Completed',
      failed: 'Failed',
      cancelled: 'Cancelled',
    }
    return labels[value] || String(value || 'Unknown')
  }

  function renderMetrics() {
    const installed = Boolean(state.tool?.installed)
    const active = state.jobs.filter((job) => job.state === 'active').length
    const queued = state.jobs.filter((job) => job.state === 'queued').length
    const completed = state.jobs.filter((job) => job.state === 'completed').length
    setText('galleryMetricTool', installed ? 'Ready' : 'Missing')
    setText('galleryMetricToolDetail', state.tool?.toolRootReady === false ? 'tool root unavailable' : 'managed gallery-dl')
    setText('galleryMetricVersion', state.tool?.version || '—')
    setText('galleryMetricActive', active)
    setText('galleryMetricQueued', queued)
    setText('galleryMetricCompleted', completed)
  }

  function rateBounds() {
    const advertisedMin = Number(state.engine?.rateLimitMinMiB)
    const advertisedMax = Number(state.engine?.rateLimitMaxMiB)
    const min = Number.isFinite(advertisedMin) && advertisedMin >= 0.1 && advertisedMin <= 1024 ? advertisedMin : 0.1
    const max = Number.isFinite(advertisedMax) && advertisedMax >= min && advertisedMax <= 1024 ? advertisedMax : 1024
    return { min, max }
  }

  function renderTool() {
    const tool = state.tool || {}
    const result = state.lastToolResult || null
    const installed = Boolean(tool.installed)
    const mutationBlocked = Boolean(tool.mutationBlocked) || hasLiveJobs()
    const rootReady = tool.toolRootReady !== false
    const acceptingJobs = state.engine?.acceptingJobs !== false
    const archiveSupported = state.engine?.archiveSupported === true
    const dateFilterSupported = state.engine?.dateFilterSupported === true
    const resumeSupported = state.engine?.resumeSupported === true
    const rateSupported = state.engine?.rateLimitSupported === true
    const archiveControl = $('galleryArchiveEnabled')
    const resumeControl = $('galleryResumeEnabled')
    const rateControl = $('galleryRateLimit')
    const dateRange = $('galleryDateRange')
    const { min: rateMin, max: rateMax } = rateBounds()

    setText('galleryToolInstalled', installed ? 'Installed' : 'Not installed')
    setText('galleryToolVersion', tool.version || '—')
    setText('galleryToolAvailable', result?.availableVersion || '—')
    setText('galleryToolMutation', mutationBlocked ? 'Blocked by active tasks' : 'Available')
    setText('galleryToolSummary', !rootReady ? 'Managed tool storage is unavailable.' : installed ? 'Verified managed gallery-dl is available.' : 'gallery-dl is not installed yet.')
    setText('galleryToolMessage', result?.message || 'Tool checks are explicit; startup never contacts the provider.')
    setText('galleryArchiveHelp', archiveSupported ? 'Skip files already recorded by this Local Engine.' : 'Archive is unavailable because a trusted state root is not available.')
    setText('galleryResumeHelp', resumeSupported ? "Retry reuses this task's managed directory. Existing .part files resume only when the remote server honors HTTP Range." : 'Resume is unavailable on this Headless API version.')
    setText('galleryDateHelp', dateFilterSupported ? 'Uses gallery-dl native post ordering. Some sites with pinned older posts can stop an “After” scan earlier than expected.' : 'Date filtering is unavailable on this Headless API version.')
    setText('galleryRateHelp', rateSupported ? `Blank = unlimited. Numeric limit: ${rateMin}–${rateMax} MiB/s.` : 'Rate limiting is unavailable on this Headless API version.')

    rateControl.min = String(rateMin)
    rateControl.max = String(rateMax)
    if (!archiveSupported) archiveControl.checked = false
    if (!resumeSupported) resumeControl.checked = false
    if (!rateSupported) rateControl.value = ''
    if (!dateFilterSupported) {
      $('galleryDateAfter').value = ''
      $('galleryDateBefore').value = ''
    }

    const busy = state.toolActionPending
    $('galleryToolCheck').disabled = busy || !rootReady
    $('galleryToolInstall').disabled = busy || !rootReady || installed || mutationBlocked
    $('galleryToolUpdate').disabled = busy || !rootReady || !installed || mutationBlocked
    $('galleryToolRemove').disabled = busy || !rootReady || !installed || mutationBlocked
    $('galleryToolInstall').classList.toggle('is-hidden', installed)
    $('galleryToolUpdate').classList.toggle('is-hidden', !installed)
    $('galleryToolRemove').classList.toggle('is-hidden', !installed)
    $('gallerySubmitButton').disabled = state.submitPending || !installed || !acceptingJobs
    $('gallerySourceUrl').disabled = state.submitPending || !installed || !acceptingJobs
    $('galleryMaxFiles').disabled = state.submitPending || !installed || !acceptingJobs
    archiveControl.disabled = state.submitPending || !installed || !acceptingJobs || !archiveSupported
    resumeControl.disabled = state.submitPending || !installed || !acceptingJobs || !resumeSupported
    rateControl.disabled = state.submitPending || !installed || !acceptingJobs || !rateSupported
    dateRange.disabled = state.submitPending || !installed || !acceptingJobs || !dateFilterSupported
  }

  function actionButton(job, action) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'action'
    button.dataset.galleryJob = job.id
    button.dataset.galleryAction = action
    button.textContent = action === 'cancel' ? 'Cancel' : 'Retry'
    return button
  }

  function renderJobs() {
    const list = $('galleryJobsList')
    list.replaceChildren()
    setText('galleryJobsMeta', `${state.jobs.length} recent task${state.jobs.length === 1 ? '' : 's'} · active tasks refresh automatically`)

    if (!state.jobs.length) {
      const empty = document.createElement('div')
      empty.className = 'empty'
      empty.textContent = 'No gallery-dl tasks yet.'
      list.appendChild(empty)
      renderMetrics()
      schedulePolling()
      return
    }

    for (const job of state.jobs) {
      const row = document.createElement('article')
      row.className = 'gallery-job-row'

      const stateCell = document.createElement('div')
      const pill = document.createElement('span')
      pill.className = 'state'
      pill.dataset.state = job.state || 'unknown'
      pill.textContent = stateLabel(job.state)
      stateCell.appendChild(pill)

      const main = document.createElement('div')
      main.className = 'gallery-job-main'
      const title = document.createElement('strong')
      title.textContent = job.title || 'Gallery task'
      const detail = document.createElement('span')
      detail.textContent = job.detail || job.advice || 'No additional status detail.'
      main.append(title, detail)

      const summary = document.createElement('div')
      summary.className = 'gallery-job-summary'
      summary.textContent = job.summary || '—'

      const actions = document.createElement('div')
      actions.className = 'gallery-job-actions'
      const allowed = Array.isArray(job.actions) ? job.actions : []
      for (const action of allowed) {
        if (action === 'cancel' || action === 'retry') actions.appendChild(actionButton(job, action))
      }
      if (!actions.childElementCount) {
        const done = document.createElement('span')
        done.className = 'muted'
        done.textContent = '—'
        actions.appendChild(done)
      }

      row.append(stateCell, main, summary, actions)
      list.appendChild(row)
    }
    renderMetrics()
    schedulePolling()
  }

  async function loadJobs() {
    const result = await api('/v1/gallery-dl/jobs?limit=100')
    state.jobs = Array.isArray(result.jobs) ? result.jobs : []
    state.tool = await api('/v1/gallery-dl/tool')
    renderTool()
    renderJobs()
  }

  async function loadGallery() {
    stopPolling()
    try {
      const [engine, jobs] = await Promise.all([
        api('/v1/gallery-dl/status'),
        api('/v1/gallery-dl/jobs?limit=100'),
      ])
      state.engine = engine
      state.jobs = Array.isArray(jobs.jobs) ? jobs.jobs : []
      state.tool = await api('/v1/gallery-dl/tool')
      renderTool()
      renderJobs()
      showError('')
    } catch (error) {
      setText('gallerySubmitStatus', 'Gallery service could not be loaded.')
      showError(error instanceof Error ? error.message : 'Unable to load gallery-dl')
    }
  }

  async function submitGallery(event) {
    event.preventDefault()
    const form = $('gallerySubmitForm')
    if (!form.reportValidity()) return
    const maxFiles = Number.parseInt($('galleryMaxFiles').value, 10)
    if (!Number.isInteger(maxFiles) || maxFiles < 1 || maxFiles > 500) {
      showError('Max files must be between 1 and 500')
      return
    }
    const archiveEnabled = state.engine?.archiveSupported === true && $('galleryArchiveEnabled').checked
    const resumeEnabled = state.engine?.resumeSupported === true && $('galleryResumeEnabled').checked
    const dateFilterSupported = state.engine?.dateFilterSupported === true
    const rateSupported = state.engine?.rateLimitSupported === true
    const dateAfter = dateFilterSupported ? $('galleryDateAfter').value.trim() : ''
    const dateBefore = dateFilterSupported ? $('galleryDateBefore').value.trim() : ''
    if (dateAfter && dateBefore && dateAfter >= dateBefore) {
      setText('gallerySubmitStatus', 'Gallery download was not queued.')
      showError('Date “After” must be earlier than Date “Before”.')
      $('galleryDateAfter').focus()
      return
    }

    const rateText = rateSupported ? $('galleryRateLimit').value.trim() : ''
    let rateLimitMiB = null
    if (rateText) {
      const parsedRate = Number(rateText)
      const { min: rateMin, max: rateMax } = rateBounds()
      if (!Number.isFinite(parsedRate) || parsedRate < rateMin || parsedRate > rateMax) {
        setText('gallerySubmitStatus', 'Gallery download was not queued.')
        showError(`Rate must be between ${rateMin} and ${rateMax} MiB/s, or left blank for unlimited.`)
        $('galleryRateLimit').focus()
        return
      }
      rateLimitMiB = parsedRate
    }

    const payload = {
      sourceUrl: $('gallerySourceUrl').value.trim(),
      maxFiles,
      archiveEnabled: Boolean(archiveEnabled),
    }
    if (resumeEnabled) payload.resumeEnabled = true
    if (dateAfter) payload.dateAfter = dateAfter
    if (dateBefore) payload.dateBefore = dateBefore
    if (rateLimitMiB !== null) payload.rateLimitMiB = rateLimitMiB

    state.submitPending = true
    renderTool()
    setText('gallerySubmitStatus', 'Queueing gallery download…')
    try {
      const result = await postJson('/v1/gallery-dl/jobs', payload)
      setText('gallerySubmitStatus', result.job?.title ? `Queued: ${result.job.title}` : 'Gallery download queued.')
      $('gallerySourceUrl').value = ''
      await loadJobs()
      showError('')
    } catch (error) {
      setText('gallerySubmitStatus', 'Gallery download was not queued.')
      showError(error instanceof Error ? error.message : 'Unable to queue gallery download')
    } finally {
      state.submitPending = false
      renderTool()
    }
  }

  async function runJobAction(jobId, action) {
    try {
      await postJson(`/v1/gallery-dl/jobs/${encodeURIComponent(jobId)}/${action}`, {})
      await loadJobs()
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : `Unable to ${action} gallery task`)
    }
  }

  async function runToolAction(action) {
    if (state.toolActionPending) return
    const payload = {}
    if (action === 'remove') {
      if (!window.confirm('Remove the managed gallery-dl tool? Existing downloaded files are not deleted.')) return
      payload.confirm = state.tool?.removeConfirmation || 'remove-gallery-dl'
    }
    state.toolActionPending = true
    renderTool()
    setText('galleryToolMessage', `${action === 'check' ? 'Checking' : `${action[0].toUpperCase()}${action.slice(1)}`} gallery-dl…`)
    try {
      const result = await postJson(`/v1/gallery-dl/tool/${action}`, payload)
      state.lastToolResult = result.result || null
      state.tool = result.tool || state.tool
      state.engine = await api('/v1/gallery-dl/status')
      renderTool()
      renderMetrics()
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : `gallery-dl ${action} failed`)
      await loadGallery().catch(() => {})
    } finally {
      state.toolActionPending = false
      renderTool()
    }
  }

  injectShell()

  document.addEventListener('click', (event) => {
    const galleryView = event.target.closest('[data-gallery-view]')
    if (galleryView) {
      showGallery()
      return
    }
    if (event.target.closest('[data-view], [data-view-jump], [data-ops-view], [data-plugin-view], [data-settings-view]')) {
      hideGallery()
      return
    }
    const jobAction = event.target.closest('[data-gallery-job][data-gallery-action]')
    if (jobAction) runJobAction(jobAction.dataset.galleryJob, jobAction.dataset.galleryAction)
  })

  $('gallerySubmitForm').addEventListener('submit', submitGallery)
  $('galleryRefreshButton').addEventListener('click', loadGallery)
  $('galleryToolCheck').addEventListener('click', () => runToolAction('check'))
  $('galleryToolInstall').addEventListener('click', () => runToolAction('install'))
  $('galleryToolUpdate').addEventListener('click', () => runToolAction('update'))
  $('galleryToolRemove').addEventListener('click', () => runToolAction('remove'))
  $('refreshButton')?.addEventListener('click', () => { if (isVisible()) loadGallery() })
})()
