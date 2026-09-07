(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const idPattern = /^[a-f0-9]{32}$/
  const playbackPathPattern = /^\/v1\/learning\/playback\/[A-Za-z0-9_-]{32,128}\/[a-f0-9]{32}$/
  const state = {
    courseId: '',
    resume: null,
    refreshTimer: 0,
    observer: null,
    media: null,
    loading: false,
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
    if (response.status === 401) throw new Error('Headless API requires a valid Bearer token')
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function selectedCourseId() {
    const value = String(document.querySelector('[data-learning-course].is-selected')?.dataset.learningCourse || '').trim().toLowerCase()
    return idPattern.test(value) ? value : ''
  }

  function publicId(value) {
    const clean = String(value || '').trim().toLowerCase()
    return idPattern.test(clean) ? clean : ''
  }

  function safeSeconds(value) {
    const seconds = Number(value)
    return Number.isFinite(seconds) && seconds > 0 ? seconds : 0
  }

  function formatTime(value) {
    const total = Math.max(0, Math.floor(safeSeconds(value)))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = total % 60
    if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    return `${minutes}:${String(seconds).padStart(2, '0')}`
  }

  function installPanel() {
    const detail = $('learningCourseDetail')
    if (!detail || $('learningPlayerPanel')) return
    const panel = document.createElement('section')
    panel.id = 'learningPlayerPanel'
    panel.className = 'learning-player-panel'
    panel.innerHTML = `
      <div class="learning-player-head">
        <div>
          <h3>Continue learning</h3>
          <p>Resume the latest unfinished local video or audio from your saved position.</p>
        </div>
        <button class="button primary" id="learningPlayerAction" type="button" disabled>Continue</button>
      </div>
      <div id="learningPlayerStatus" class="learning-player-status" aria-live="polite">Select a course to continue.</div>
      <div id="learningPlayerStage" class="learning-player-stage is-hidden"></div>`
    const sections = $('learningSections')
    if (sections && sections.parentNode === detail) detail.insertBefore(panel, sections)
    else detail.appendChild(panel)
    $('learningPlayerAction')?.addEventListener('click', () => startPlayback())
  }

  function stopMedia() {
    const media = state.media
    state.media = null
    if (!media) return
    try { media.pause() } catch (_) {}
    media.removeAttribute('src')
    try { media.load() } catch (_) {}
    media.remove()
    const stage = $('learningPlayerStage')
    if (stage) {
      stage.textContent = ''
      stage.classList.add('is-hidden')
    }
  }

  function setStatus(message, tone = '') {
    const node = $('learningPlayerStatus')
    if (!node) return
    node.textContent = String(message || '')
    node.dataset.tone = tone
  }

  function setAction(label, enabled) {
    const button = $('learningPlayerAction')
    if (!button) return
    button.textContent = label
    button.disabled = !enabled || state.loading
  }

  function actionableResume() {
    const resume = state.resume
    if (!resume || typeof resume !== 'object') return null
    const item = resume.item && typeof resume.item === 'object' ? resume.item : null
    const mediaId = publicId(item?.mediaId)
    const itemId = publicId(item?.id)
    const mediaType = String(item?.mediaType || '').toLowerCase()
    const resumeState = String(resume.state || '')
    if (!item || !mediaId || !itemId || !['video', 'audio'].includes(mediaType) || !['resume', 'start'].includes(resumeState)) return null
    return { item, mediaId, itemId, mediaType, resumeState }
  }

  function renderResume() {
    const resume = state.resume
    if (!resume || typeof resume !== 'object') {
      setAction('Continue', false)
      setStatus('Resume state is unavailable.')
      return
    }
    const target = actionableResume()
    if (target) {
      const title = String(target.item.title || 'Lecture')
      if (target.resumeState === 'resume') {
        const progress = safeSeconds(resume.progressSeconds)
        setAction(`Continue · ${formatTime(progress)}`, true)
        setStatus(`${title} · saved at ${formatTime(progress)}`)
      } else {
        setAction('Start course', true)
        setStatus(`${title} · ready to start`)
      }
      return
    }
    const resumeState = String(resume.state || '')
    if (resumeState === 'completed') {
      setAction('Completed', false)
      setStatus('All available local lessons are completed.', 'success')
    } else if (resumeState === 'empty') {
      setAction('Unavailable', false)
      setStatus('No local playable video or audio is available for this course.')
    } else {
      setAction('Continue', false)
      setStatus('This course does not have a safe playable resume target.')
    }
  }

  async function refreshCurrent() {
    installPanel()
    const courseId = selectedCourseId()
    if (!courseId) {
      state.courseId = ''
      state.resume = null
      stopMedia()
      renderResume()
      return
    }
    try {
      const payload = await api(`/v1/learning/courses/${encodeURIComponent(courseId)}/resume`)
      if (courseId !== selectedCourseId()) return
      if (state.courseId && state.courseId !== courseId) stopMedia()
      state.courseId = courseId
      state.resume = payload?.resume && typeof payload.resume === 'object' ? payload.resume : null
      renderResume()
    } catch (error) {
      if (courseId !== selectedCourseId()) return
      state.courseId = courseId
      state.resume = null
      stopMedia()
      setAction('Continue', false)
      setStatus(error instanceof Error ? error.message : 'Unable to resolve course resume target.', 'error')
    }
  }

  async function issuePlayback(mediaId) {
    const payload = await api(`/v1/learning/media/${encodeURIComponent(mediaId)}/playback-ticket`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    })
    const playback = payload?.playback && typeof payload.playback === 'object' ? payload.playback : null
    const url = String(playback?.url || '')
    if (publicId(playback?.mediaId) !== mediaId || !playbackPathPattern.test(url)) {
      throw new Error('Playback ticket response is invalid')
    }
    return url
  }

  function mountMedia(target, playbackUrl) {
    const stage = $('learningPlayerStage')
    if (!stage) throw new Error('Player surface is unavailable')
    stopMedia()
    const media = document.createElement(target.mediaType === 'audio' ? 'audio' : 'video')
    media.className = 'learning-player-media'
    media.controls = true
    media.preload = 'metadata'
    media.setAttribute('playsinline', '')
    const startSeconds = target.resumeState === 'resume' ? safeSeconds(state.resume?.progressSeconds) : 0
    media.addEventListener('loadedmetadata', () => {
      if (!startSeconds || !Number.isFinite(media.duration) || media.duration <= 0) return
      const ceiling = Math.max(0, media.duration - 0.25)
      media.currentTime = Math.min(startSeconds, ceiling)
    }, { once: true })
    media.addEventListener('error', () => {
      setStatus('Playback stopped because the local media stream became unavailable.', 'error')
    })
    stage.textContent = ''
    stage.appendChild(media)
    stage.classList.remove('is-hidden')
    state.media = media
    media.src = playbackUrl
    media.load()
    return media
  }

  async function startPlayback() {
    if (state.loading) return
    const target = actionableResume()
    if (!target) {
      renderResume()
      return
    }
    state.loading = true
    setAction(target.resumeState === 'resume' ? 'Opening…' : 'Starting…', false)
    setStatus('Preparing a secure local playback stream…')
    try {
      const playbackUrl = await issuePlayback(target.mediaId)
      if (target !== actionableResume() && target.mediaId !== publicId(state.resume?.item?.mediaId)) return
      const media = mountMedia(target, playbackUrl)
      setStatus(`${String(target.item.title || 'Lecture')} · playing locally`, 'success')
      try {
        await media.play()
      } catch (_) {
        setStatus('Player is ready. Press play to begin.')
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to start local playback.', 'error')
    } finally {
      state.loading = false
      renderResume()
    }
  }

  function scheduleRefresh(delay = 80) {
    window.clearTimeout(state.refreshTimer)
    state.refreshTimer = window.setTimeout(refreshCurrent, delay)
  }

  function observeLearning() {
    const sections = $('learningSections')
    if (!sections || state.observer) return
    state.observer = new MutationObserver(() => scheduleRefresh())
    state.observer.observe(sections, { childList: true, subtree: true })
  }

  document.addEventListener('DOMContentLoaded', () => {
    installPanel()
    observeLearning()
  })

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return
    if (target.closest('[data-learning-course]')) scheduleRefresh(140)
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(state.refreshTimer)
    state.observer?.disconnect()
    stopMedia()
  })
})()
