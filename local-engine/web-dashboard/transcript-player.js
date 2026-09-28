(() => {
  'use strict'

  const mediaIdPattern = /^[a-f0-9]{16,64}$/
  const playbackPathPattern = /^\/v1\/media\/playback\/[A-Za-z0-9_-]{32,128}\/[a-f0-9]{16,64}$/
  const state = {
    media: null,
    mediaId: '',
    mediaType: '',
    activeButton: null,
    segments: [],
    generation: 0,
    observer: null,
  }

  const $ = (id) => document.getElementById(id)

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = 'Bearer ' + token
    return headers
  }

  function publicMediaId(value) {
    const clean = String(value || '').trim().toLowerCase()
    return mediaIdPattern.test(clean) ? clean : ''
  }

  function safeSeconds(value) {
    const seconds = Number(value)
    return Number.isFinite(seconds) && seconds >= 0 ? seconds : 0
  }

  function formatTime(value) {
    const total = Math.max(0, Math.floor(safeSeconds(value)))
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = total % 60
    if (hours) return hours + ':' + String(minutes).padStart(2, '0') + ':' + String(seconds).padStart(2, '0')
    return minutes + ':' + String(seconds).padStart(2, '0')
  }

  function mediaTitle(mediaId) {
    const node = document.querySelector('[data-transcript-media="' + mediaId + '"] strong')
    return String(node?.textContent || mediaId)
  }

  function installPlayer() {
    const content = document.querySelector('#transcriptView .transcript-content')
    if (!content || $('transcriptPlayer')) return

    const panel = document.createElement('section')
    panel.id = 'transcriptPlayer'
    panel.className = 'transcript-player'
    panel.setAttribute('aria-label', 'Transcript media player')

    const head = document.createElement('div')
    head.className = 'transcript-player-head'
    const copy = document.createElement('div')
    const title = document.createElement('strong')
    title.textContent = 'Player'
    const description = document.createElement('span')
    description.textContent = 'Click a transcript timestamp to open the indexed local media at that position.'
    copy.append(title, description)

    const status = document.createElement('div')
    status.id = 'transcriptPlayerStatus'
    status.className = 'transcript-player-status'
    status.setAttribute('aria-live', 'polite')
    status.textContent = 'Choose a transcript timestamp to begin.'

    head.append(copy, status)

    const stage = document.createElement('div')
    stage.id = 'transcriptPlayerStage'
    stage.className = 'transcript-player-stage is-hidden'

    panel.append(head, stage)
    content.insertBefore(panel, content.firstChild)
  }

  function setStatus(message, tone = '') {
    const node = $('transcriptPlayerStatus')
    if (!node) return
    node.textContent = String(message || '')
    node.dataset.tone = tone
  }

  function clearActiveSegment() {
    const previous = state.activeButton?.closest('.segment')
    if (previous) previous.classList.remove('is-active')
    if (state.activeButton) state.activeButton.removeAttribute('aria-current')
    state.activeButton = null
  }

  function collectSegments(mediaId = state.mediaId) {
    const clean = publicMediaId(mediaId)
    if (!clean) {
      state.segments = []
      clearActiveSegment()
      return
    }
    state.segments = Array.from(document.querySelectorAll('[data-transcript-seek]'))
      .filter((button) => publicMediaId(button.dataset.transcriptMediaId) === clean)
      .map((button) => {
        const start = safeSeconds(button.dataset.transcriptSeek)
        const rawEnd = Number(button.dataset.transcriptEnd)
        const end = Number.isFinite(rawEnd) && rawEnd > start ? rawEnd : start + 0.5
        return { button, start, end }
      })
      .sort((a, b) => a.start - b.start || a.end - b.end)
    clearActiveSegment()
  }

  function setActiveSegment(entry) {
    if (state.activeButton === entry?.button) return
    clearActiveSegment()
    if (!entry?.button) return
    state.activeButton = entry.button
    state.activeButton.setAttribute('aria-current', 'true')
    const row = state.activeButton.closest('.segment')
    if (row) {
      row.classList.add('is-active')
      row.scrollIntoView({ block: 'nearest', behavior: 'auto' })
    }
  }

  function syncActiveSegment(seconds) {
    const rows = state.segments
    if (!rows.length) {
      clearActiveSegment()
      return
    }
    let low = 0
    let high = rows.length - 1
    let candidate = -1
    while (low <= high) {
      const mid = Math.floor((low + high) / 2)
      if (rows[mid].start <= seconds) {
        candidate = mid
        low = mid + 1
      } else {
        high = mid - 1
      }
    }
    const entry = candidate >= 0 ? rows[candidate] : null
    setActiveSegment(entry && seconds < entry.end ? entry : null)
  }

  async function issuePlayback(mediaId) {
    const response = await fetch('/v1/media/' + encodeURIComponent(mediaId) + '/playback-ticket', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: '{}',
      cache: 'no-store',
    })
    if (response.status === 401) throw new Error('Headless API requires a valid Bearer token')
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || 'Unable to create media playback ticket')
    const playback = payload?.playback && typeof payload.playback === 'object' ? payload.playback : null
    const returnedId = publicMediaId(playback?.mediaId)
    const mediaType = String(playback?.mediaType || '')
    const url = String(playback?.url || '')
    if (
      returnedId !== mediaId ||
      !['video', 'audio'].includes(mediaType) ||
      !playbackPathPattern.test(url)
    ) {
      throw new Error('Playback ticket response is invalid')
    }
    return { mediaType, url }
  }

  function stopPlayer({ keepStatus = false } = {}) {
    state.generation += 1
    const media = state.media
    state.media = null
    state.mediaId = ''
    state.mediaType = ''
    state.segments = []
    clearActiveSegment()
    if (media) {
      try { media.pause() } catch (_) {}
      media.removeAttribute('src')
      try { media.load() } catch (_) {}
      media.remove()
    }
    const stage = $('transcriptPlayerStage')
    if (stage) {
      stage.textContent = ''
      stage.classList.add('is-hidden')
    }
    if (!keepStatus) setStatus('Choose a transcript timestamp to begin.')
  }

  function seekMounted(seconds) {
    const media = state.media
    if (!media) return false
    const target = safeSeconds(seconds)
    if (Number.isFinite(media.duration) && media.duration > 0) {
      media.currentTime = Math.min(target, Math.max(0, media.duration - 0.05))
    } else {
      media.currentTime = target
    }
    syncActiveSegment(media.currentTime)
    const playAttempt = media.play()
    if (playAttempt && typeof playAttempt.catch === 'function') {
      playAttempt.catch(() => setStatus(mediaTitle(state.mediaId) + ' · ready at ' + formatTime(target) + '. Press play to continue.'))
    }
    return true
  }

  function mountPlayer(mediaId, mediaType, playbackUrl, seconds) {
    const stage = $('transcriptPlayerStage')
    if (!stage) throw new Error('Transcript player surface is unavailable')
    stopPlayer({ keepStatus: true })

    const media = document.createElement(mediaType === 'audio' ? 'audio' : 'video')
    media.className = 'transcript-player-media'
    media.controls = true
    media.preload = 'metadata'
    media.setAttribute('playsinline', '')

    state.media = media
    state.mediaId = mediaId
    state.mediaType = mediaType
    collectSegments(mediaId)

    const target = safeSeconds(seconds)
    media.addEventListener('loadedmetadata', () => {
      if (state.media !== media) return
      seekMounted(target)
    }, { once: true })
    media.addEventListener('timeupdate', () => {
      if (state.media === media) syncActiveSegment(media.currentTime)
    })
    media.addEventListener('seeked', () => {
      if (state.media === media) syncActiveSegment(media.currentTime)
    })
    media.addEventListener('play', () => {
      if (state.media === media) setStatus(mediaTitle(mediaId) + ' · playing at ' + formatTime(media.currentTime), 'success')
    })
    media.addEventListener('pause', () => {
      if (state.media === media && !media.ended) setStatus(mediaTitle(mediaId) + ' · paused at ' + formatTime(media.currentTime))
    })
    media.addEventListener('ended', () => {
      if (state.media === media) {
        clearActiveSegment()
        setStatus(mediaTitle(mediaId) + ' · playback complete', 'success')
      }
    })
    media.addEventListener('error', () => {
      if (state.media === media) setStatus('Playback stopped because the local media stream became unavailable.', 'error')
    })

    stage.textContent = ''
    stage.appendChild(media)
    stage.classList.remove('is-hidden')
    media.src = playbackUrl
    media.load()
  }

  async function openAtTimestamp(button) {
    installPlayer()
    const mediaId = publicMediaId(button?.dataset?.transcriptMediaId)
    const seconds = safeSeconds(button?.dataset?.transcriptSeek)
    if (!mediaId) {
      setStatus('This transcript row is not linked to a playable Library item.', 'error')
      return
    }
    if (state.media && state.mediaId === mediaId) {
      seekMounted(seconds)
      return
    }

    const generation = ++state.generation
    setStatus('Preparing secure local playback…')
    try {
      const playback = await issuePlayback(mediaId)
      if (generation !== state.generation) return
      mountPlayer(mediaId, playback.mediaType, playback.url, seconds)
    } catch (error) {
      if (generation !== state.generation) return
      setStatus(error instanceof Error ? error.message : 'Unable to open local media.', 'error')
    }
  }

  function observeTranscriptResults() {
    const results = $('transcriptResults')
    if (!results || state.observer) return
    state.observer = new MutationObserver(() => {
      if (state.mediaId) collectSegments(state.mediaId)
    })
    state.observer.observe(results, { childList: true, subtree: true })
  }

  document.addEventListener('DOMContentLoaded', () => {
    installPlayer()
    observeTranscriptResults()
  })

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return

    const timestamp = target.closest('[data-transcript-seek]')
    if (timestamp) {
      event.preventDefault()
      void openAtTimestamp(timestamp)
      return
    }

    const mediaChoice = target.closest('[data-transcript-media]')
    if (mediaChoice) {
      const nextId = publicMediaId(mediaChoice.dataset.transcriptMedia)
      if (state.media && nextId && nextId !== state.mediaId) stopPlayer()
    }
  })

  window.addEventListener('beforeunload', () => {
    state.observer?.disconnect()
    stopPlayer({ keepStatus: true })
  })
})()
