(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const terminalJobs = new Set(['completed', 'failed', 'cancelled'])
  const terminalSync = new Set(['synced', 'failed'])
  const state = {
    courses: [],
    providers: [],
    selectedCourseId: '',
    currentJobId: '',
    currentStatus: null,
    pollTimer: 0,
  }

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: authHeaders(options.headers || {}), cache: 'no-store' })
    if (response.status === 401) {
      $('credentialsPanel')?.classList.remove('is-hidden')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function postJson(path, payload = {}) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  }

  function showError(message) {
    const notice = $('errorNotice')
    if (!notice) return
    $('errorText').textContent = message || ''
    notice.classList.toggle('is-hidden', !message)
  }

  function installWorkspace() {
    const nav = document.querySelector('.sidebar nav')
    const main = document.querySelector('main')
    if (!nav || !main || $('learningView')) return

    const navButton = document.createElement('button')
    navButton.className = 'nav-item'
    navButton.type = 'button'
    navButton.dataset.learningView = 'learning'
    navButton.textContent = 'Learning'
    nav.appendChild(navButton)

    const view = document.createElement('section')
    view.id = 'learningView'
    view.className = 'view is-hidden learning-view'
    view.innerHTML = `
      <section class="panel learning-download-panel">
        <div class="panel-header">
          <div><h2>Managed course download</h2><p>Download an authorized course using an existing browser login and sync it into Learning.</p></div>
          <button class="button secondary" id="learningRefreshButton" type="button">Refresh</button>
        </div>
        <form id="learningDownloadForm" class="learning-form">
          <label class="field learning-source"><span>Course URL</span><input id="learningSourceUrl" type="url" required maxlength="1200" autocomplete="off" placeholder="https://www.udemy.com/course/..."></label>
          <label class="field"><span>Provider</span><select id="learningProvider"><option value="auto">Auto</option><option value="udemy">Udemy</option></select></label>
          <label class="field"><span>Browser login</span><select id="learningBrowser"><option value="none">None</option><option value="edge">Edge</option><option value="chrome">Chrome</option><option value="firefox">Firefox</option><option value="brave">Brave</option></select></label>
          <label class="field"><span>Target course</span><select id="learningTargetCourse"><option value="">Create new course</option></select></label>
          <label class="field"><span>Course name</span><input id="learningCourseName" maxlength="180" placeholder="Optional when creating a course"></label>
          <div class="learning-form-actions"><button class="button primary" id="learningDownloadButton" type="submit">Start download</button></div>
        </form>
        <div id="learningDownloadStatus" class="learning-status is-hidden" aria-live="polite"></div>
      </section>

      <div class="learning-columns">
        <section class="panel learning-course-list-panel">
          <div class="panel-header"><div><h2>Courses</h2><p id="learningCourseCount">0 courses</p></div></div>
          <div id="learningCourseList" class="learning-course-list"><div class="empty">No courses.</div></div>
        </section>
        <section class="panel learning-detail-panel">
          <div id="learningCourseEmpty" class="empty">Select a course to inspect its sections and lectures.</div>
          <div id="learningCourseDetail" class="is-hidden">
            <div class="learning-detail-head"><div><h2 id="learningDetailTitle">Course</h2><p id="learningDetailMeta"></p></div><span id="learningDetailProvider" class="ops-status"></span></div>
            <div id="learningSections" class="learning-sections"></div>
          </div>
        </section>
      </div>`
    main.appendChild(view)
  }

  function closeLearningView() {
    $('learningView')?.classList.add('is-hidden')
    document.querySelectorAll('[data-learning-view]').forEach((button) => button.classList.remove('is-active'))
  }

  async function showLearningView() {
    document.querySelectorAll('main .view').forEach((view) => view.classList.add('is-hidden'))
    document.querySelectorAll('.sidebar .nav-item').forEach((button) => button.classList.remove('is-active'))
    $('learningView')?.classList.remove('is-hidden')
    document.querySelector('[data-learning-view="learning"]')?.classList.add('is-active')
    if ($('viewTitle')) $('viewTitle').textContent = 'Learning'
    await loadLearning()
  }

  function providerOptions() {
    const discovered = state.providers
      .filter((provider) => provider && provider.downloadAvailable !== false)
      .map((provider) => String(provider.id || '').trim().toLowerCase())
      .filter(Boolean)
    const values = ['auto', ...new Set(discovered)]
    if (!values.includes('udemy')) values.push('udemy')
    $('learningProvider').innerHTML = values.map((value) => `<option value="${esc(value)}">${esc(value === 'auto' ? 'Auto' : value === 'udemy' ? 'Udemy' : value)}</option>`).join('')
  }

  function renderTargetCourses() {
    const select = $('learningTargetCourse')
    const current = select.value
    select.innerHTML = '<option value="">Create new course</option>' + state.courses.map((course) => `<option value="${esc(course.id)}">${esc(course.name || 'Untitled course')}</option>`).join('')
    if (state.courses.some((course) => course.id === current)) select.value = current
  }

  function renderCourses() {
    $('learningCourseCount').textContent = `${state.courses.length} course${state.courses.length === 1 ? '' : 's'}`
    $('learningCourseList').innerHTML = state.courses.length ? state.courses.map((course) => {
      const active = course.id === state.selectedCourseId ? ' is-selected' : ''
      const provider = course.provider || 'generic'
      return `<button class="learning-course-row${active}" data-learning-course="${esc(course.id)}" type="button"><strong>${esc(course.name || 'Untitled course')}</strong><span>${esc(provider)}${course.sourceUrl ? ` · ${esc(course.sourceUrl)}` : ''}</span></button>`
    }).join('') : '<div class="empty">No courses yet. Start a managed download above.</div>'
    renderTargetCourses()
  }

  function itemRow(item) {
    const progress = Number(item.progressSeconds) || 0
    const completion = item.completed ? 'Completed' : progress > 0 ? `${Math.round(progress)}s watched` : 'Not started'
    return `<article class="learning-lecture"><div><strong>${esc(item.title || item.fileName || 'Lecture')}</strong><span>${esc(completion)}</span></div>${item.providerItemId ? `<span class="learning-provider-id">${esc(item.providerItemId)}</span>` : ''}</article>`
  }

  function renderCourseDetail(payload) {
    const course = payload.course || {}
    const items = Array.isArray(payload.items) ? payload.items : []
    const sections = Array.isArray(payload.sections) ? [...payload.sections] : []
    sections.sort((a, b) => (Number(a.position) || 0) - (Number(b.position) || 0))
    const bySection = new Map(sections.map((section) => [String(section.id || ''), []]))
    const unsectioned = []
    for (const item of items) {
      const key = String(item.sectionId || '')
      if (key && bySection.has(key)) bySection.get(key).push(item)
      else unsectioned.push(item)
    }

    $('learningCourseEmpty').classList.add('is-hidden')
    $('learningCourseDetail').classList.remove('is-hidden')
    $('learningDetailTitle').textContent = course.name || 'Untitled course'
    $('learningDetailMeta').textContent = course.sourceUrl || 'Local / manual course'
    $('learningDetailProvider').textContent = course.provider || 'generic'

    const blocks = sections.map((section) => {
      const rows = bySection.get(String(section.id || '')) || []
      return `<section class="learning-section"><div class="learning-section-head"><strong>${esc(section.title || 'Section')}</strong><span>${rows.length} lecture${rows.length === 1 ? '' : 's'}</span></div><div class="learning-lectures">${rows.map(itemRow).join('') || '<div class="empty compact-empty">No lectures in this section.</div>'}</div></section>`
    })
    if (unsectioned.length) blocks.push(`<section class="learning-section"><div class="learning-section-head"><strong>Unsectioned</strong><span>${unsectioned.length} item${unsectioned.length === 1 ? '' : 's'}</span></div><div class="learning-lectures">${unsectioned.map(itemRow).join('')}</div></section>`)
    $('learningSections').innerHTML = blocks.join('') || '<div class="empty">This course has no items yet.</div>'
  }

  async function selectCourse(courseId) {
    state.selectedCourseId = String(courseId || '')
    renderCourses()
    if (!state.selectedCourseId) return
    const detail = await api(`/v1/learning/courses/${encodeURIComponent(state.selectedCourseId)}?itemLimit=2000`)
    renderCourseDetail(detail)
  }

  function renderDownloadStatus(payload) {
    state.currentStatus = payload
    const status = $('learningDownloadStatus')
    const job = payload?.job || {}
    const session = payload?.session || {}
    const jobState = String(job.state || 'queued')
    const syncState = String(session.syncState || 'pending')
    const outputCount = Number(session.outputCount) || 0
    const syncedCount = Number(session.syncedCount) || 0
    const canCancel = job.id && !terminalJobs.has(jobState)
    const canSync = jobState === 'completed' && syncState === 'failed'
    status.classList.remove('is-hidden')
    status.innerHTML = `<div><strong>${esc(jobState)}</strong><span>Course sync: ${esc(syncState)} · ${syncedCount}/${outputCount} indexed</span></div><div class="learning-status-actions">${canCancel ? '<button class="button secondary danger-button" data-learning-cancel type="button">Cancel</button>' : ''}${canSync ? '<button class="button secondary" data-learning-sync type="button">Retry sync</button>' : ''}</div>`
  }

  function stopPolling() {
    window.clearTimeout(state.pollTimer)
    state.pollTimer = 0
  }

  function shouldPoll(payload) {
    const jobState = String(payload?.job?.state || '')
    const syncState = String(payload?.session?.syncState || '')
    if (!jobState) return false
    if (!terminalJobs.has(jobState)) return true
    return jobState === 'completed' && !terminalSync.has(syncState)
  }

  async function pollDownload() {
    stopPolling()
    if (!state.currentJobId) return
    try {
      const payload = await api(`/v1/learning/providers/downloads/${encodeURIComponent(state.currentJobId)}`)
      renderDownloadStatus(payload)
      if (payload.session?.courseId) {
        state.selectedCourseId = String(payload.session.courseId)
      }
      if (shouldPoll(payload)) state.pollTimer = window.setTimeout(pollDownload, 1400)
      else {
        await loadCourses()
        if (state.selectedCourseId) await selectCourse(state.selectedCourseId)
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to refresh course download')
    }
  }

  async function submitDownload() {
    const sourceUrl = $('learningSourceUrl').value.trim()
    if (!sourceUrl) throw new Error('Course URL is required')
    const payload = {
      sourceUrl,
      provider: $('learningProvider').value || 'auto',
      browser: $('learningBrowser').value || 'none',
      courseName: $('learningCourseName').value.trim(),
    }
    const courseId = $('learningTargetCourse').value
    if (courseId) payload.courseId = courseId
    $('learningDownloadButton').disabled = true
    try {
      const result = await postJson('/v1/learning/providers/download', payload)
      state.currentJobId = String(result.job?.id || '')
      state.selectedCourseId = String(result.course?.id || courseId || '')
      renderDownloadStatus(result)
      await loadCourses()
      if (state.selectedCourseId) await selectCourse(state.selectedCourseId)
      if (state.currentJobId) state.pollTimer = window.setTimeout(pollDownload, 800)
    } finally {
      $('learningDownloadButton').disabled = false
    }
  }

  async function cancelDownload() {
    if (!state.currentJobId) return
    await api(`/v1/jobs/${encodeURIComponent(state.currentJobId)}/cancel`, { method: 'POST' })
    await pollDownload()
  }

  async function retrySync() {
    if (!state.currentJobId) return
    const result = await postJson(`/v1/learning/providers/downloads/${encodeURIComponent(state.currentJobId)}/sync`)
    renderDownloadStatus(result)
    await loadCourses()
    if (state.selectedCourseId) await selectCourse(state.selectedCourseId)
  }

  async function loadCourses() {
    const payload = await api('/v1/learning/courses?limit=500')
    state.courses = Array.isArray(payload.courses) ? payload.courses : []
    renderCourses()
  }

  async function loadLearning() {
    try {
      const [courses, providers] = await Promise.all([
        api('/v1/learning/courses?limit=500'),
        api('/v1/learning/providers'),
      ])
      state.courses = Array.isArray(courses.courses) ? courses.courses : []
      state.providers = Array.isArray(providers.providers) ? providers.providers : []
      providerOptions()
      renderCourses()
      if (state.selectedCourseId && state.courses.some((course) => course.id === state.selectedCourseId)) await selectCourse(state.selectedCourseId)
      else if (state.courses.length) await selectCourse(state.courses[0].id)
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load Learning workspace')
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    installWorkspace()
    $('learningDownloadForm')?.addEventListener('submit', (event) => {
      event.preventDefault()
      submitDownload().catch((error) => showError(error instanceof Error ? error.message : 'Course download failed'))
    })
    $('learningRefreshButton')?.addEventListener('click', () => loadLearning())
  })

  document.addEventListener('click', (event) => {
    const learningNav = event.target.closest('[data-learning-view]')
    if (learningNav) {
      showLearningView().catch((error) => showError(error instanceof Error ? error.message : 'Unable to open Learning'))
      return
    }
    const navItem = event.target.closest('.sidebar .nav-item')
    if (navItem) closeLearningView()
    const course = event.target.closest('[data-learning-course]')
    if (course) selectCourse(course.dataset.learningCourse).catch((error) => showError(error instanceof Error ? error.message : 'Unable to load course'))
    if (event.target.closest('[data-learning-cancel]')) cancelDownload().catch((error) => showError(error instanceof Error ? error.message : 'Unable to cancel course download'))
    if (event.target.closest('[data-learning-sync]')) retrySync().catch((error) => showError(error instanceof Error ? error.message : 'Unable to sync course'))
  })

  window.addEventListener('beforeunload', stopPolling)
})()
