(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const idPattern = /^[a-f0-9]{32}$/
  const state = {
    courseId: '',
    itemId: '',
    notes: [],
    loading: false,
    observer: null,
    refreshTimer: 0,
    requestSerial: 0,
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

  function publicId(value) {
    const clean = String(value || '').trim().toLowerCase()
    return idPattern.test(clean) ? clean : ''
  }

  function selectedCourseId() {
    return publicId(document.querySelector('[data-learning-course].is-selected')?.dataset.learningCourse)
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
    if (hours) return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
    return `${minutes}:${String(seconds).padStart(2, '0')}`
  }

  function makeElement(tag, className = '', text = '') {
    const node = document.createElement(tag)
    if (className) node.className = className
    if (text) node.textContent = text
    return node
  }

  function installPanel() {
    const detail = $('learningCourseDetail')
    if (!detail || $('learningNotesPanel')) return

    const panel = makeElement('section', 'learning-notes-panel')
    panel.id = 'learningNotesPanel'
    panel.setAttribute('aria-labelledby', 'learningNotesTitle')

    const head = makeElement('div', 'learning-notes-head')
    const titleWrap = makeElement('div')
    const title = makeElement('h3', '', 'Timestamp notes')
    title.id = 'learningNotesTitle'
    const helper = makeElement('p', '', 'Capture a note at the current local playback position and jump back to it later.')
    titleWrap.append(title, helper)
    const count = makeElement('span', 'learning-notes-count', '0 notes')
    count.id = 'learningNotesCount'
    head.append(titleWrap, count)

    const form = document.createElement('form')
    form.id = 'learningNotesForm'
    form.className = 'learning-notes-form'
    const label = document.createElement('label')
    label.htmlFor = 'learningNoteBody'
    label.textContent = 'Note'
    const textarea = document.createElement('textarea')
    textarea.id = 'learningNoteBody'
    textarea.rows = 3
    textarea.maxLength = 20000
    textarea.placeholder = 'Write a note for this moment…'
    textarea.autocomplete = 'off'
    const actions = makeElement('div', 'learning-notes-actions')
    const timestamp = makeElement('span', 'learning-notes-timestamp', 'At 0:00')
    timestamp.id = 'learningNoteTimestamp'
    const saveButton = makeElement('button', 'button primary', 'Save note')
    saveButton.id = 'learningNoteSave'
    saveButton.type = 'submit'
    actions.append(timestamp, saveButton)
    label.appendChild(textarea)
    form.append(label, actions)

    const status = makeElement('div', 'learning-notes-status', 'Select a course to view notes.')
    status.id = 'learningNotesStatus'
    status.setAttribute('aria-live', 'polite')
    status.setAttribute('role', 'status')

    const list = makeElement('div', 'learning-notes-list')
    list.id = 'learningNotesList'

    panel.append(head, form, status, list)
    const sections = $('learningSections')
    if (sections && sections.parentNode === detail) detail.insertBefore(panel, sections)
    else detail.appendChild(panel)

    form.addEventListener('submit', (event) => {
      event.preventDefault()
      void saveNote()
    })
    textarea.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        if (!state.loading) void saveNote()
      }
    })
    panel.addEventListener('click', (event) => {
      const target = event.target
      if (!(target instanceof Element)) return
      const seek = target.closest('[data-learning-note-seek]')
      if (seek) {
        seekToNote(seek.dataset.learningNoteSeek)
        return
      }
      const remove = target.closest('[data-learning-note-delete]')
      if (remove) void deleteNote(remove.dataset.learningNoteDelete)
    })
    syncControls()
  }

  function setStatus(message, tone = '') {
    const node = $('learningNotesStatus')
    if (!node) return
    node.textContent = String(message || '')
    node.dataset.tone = tone
  }

  function activeSeconds() {
    const media = document.querySelector('.learning-player-media')
    if (media instanceof HTMLMediaElement && Number.isFinite(media.currentTime)) return safeSeconds(media.currentTime)
    return currentResumeSeconds()
  }

  function currentResumeSeconds() {
    const status = String($('learningPlayerStatus')?.textContent || '')
    const match = status.match(/saved at\s+(?:(\d+):)?(\d+):(\d{2})/i)
    if (!match) return 0
    const hours = Number(match[1] || 0)
    const minutes = Number(match[2] || 0)
    const seconds = Number(match[3] || 0)
    return safeSeconds((hours * 3600) + (minutes * 60) + seconds)
  }

  function updateTimestampPreview() {
    const node = $('learningNoteTimestamp')
    if (node) node.textContent = `At ${formatTime(activeSeconds())}`
  }

  function syncControls() {
    const textarea = $('learningNoteBody')
    const save = $('learningNoteSave')
    const enabled = Boolean(state.itemId) && !state.loading
    if (textarea) textarea.disabled = !enabled
    if (save) {
      save.disabled = !enabled
      save.textContent = state.loading ? 'Saving…' : 'Save note'
    }
    updateTimestampPreview()
  }

  function renderNotes() {
    const list = $('learningNotesList')
    const count = $('learningNotesCount')
    if (!list || !count) return
    count.textContent = `${state.notes.length} note${state.notes.length === 1 ? '' : 's'}`
    list.textContent = ''

    if (!state.itemId) {
      const empty = makeElement('div', 'learning-notes-empty', 'Choose a playable course item to view timestamp notes.')
      list.appendChild(empty)
      return
    }
    if (!state.notes.length) {
      const empty = makeElement('div', 'learning-notes-empty', 'No notes for this lecture yet.')
      list.appendChild(empty)
      return
    }

    for (const note of state.notes) {
      const noteId = publicId(note?.id)
      if (!noteId) continue
      const row = makeElement('article', 'learning-note-row')
      const main = makeElement('div', 'learning-note-main')
      const seek = makeElement('button', 'learning-note-time', formatTime(note?.timestampSeconds))
      seek.type = 'button'
      seek.dataset.learningNoteSeek = String(safeSeconds(note?.timestampSeconds))
      seek.setAttribute('aria-label', `Jump to ${formatTime(note?.timestampSeconds)}`)
      const body = makeElement('p', 'learning-note-body')
      body.textContent = String(note?.body || '')
      main.append(seek, body)
      const remove = makeElement('button', 'button secondary learning-note-delete', 'Delete')
      remove.type = 'button'
      remove.dataset.learningNoteDelete = noteId
      remove.setAttribute('aria-label', `Delete note at ${formatTime(note?.timestampSeconds)}`)
      row.append(main, remove)
      list.appendChild(row)
    }
  }

  function resolveResumeItem(payload) {
    const resume = payload?.resume && typeof payload.resume === 'object' ? payload.resume : null
    const itemId = publicId(resume?.item?.id)
    const stateName = String(resume?.state || '')
    if (!itemId || !['resume', 'start'].includes(stateName)) return ''
    return itemId
  }

  async function loadNotesForItem(itemId) {
    const payload = await api(`/v1/learning/items/${encodeURIComponent(itemId)}/notes?limit=1000`)
    if (publicId(payload?.itemId) !== itemId) throw new Error('Timestamp note response is invalid')
    return Array.isArray(payload.notes) ? payload.notes : []
  }

  async function refreshCurrent() {
    installPanel()
    const courseId = selectedCourseId()
    const serial = ++state.requestSerial
    if (!courseId) {
      state.courseId = ''
      state.itemId = ''
      state.notes = []
      setStatus('Select a course to view notes.')
      renderNotes()
      syncControls()
      return
    }

    setStatus('Loading timestamp notes…')
    try {
      const resumePayload = await api(`/v1/learning/courses/${encodeURIComponent(courseId)}/resume`)
      if (serial !== state.requestSerial || courseId !== selectedCourseId()) return
      const itemId = resolveResumeItem(resumePayload)
      state.courseId = courseId
      state.itemId = itemId
      if (!itemId) {
        state.notes = []
        setStatus('No active local lecture is available for timestamp notes.')
        renderNotes()
        syncControls()
        return
      }
      const notes = await loadNotesForItem(itemId)
      if (serial !== state.requestSerial || itemId !== state.itemId) return
      state.notes = notes
      setStatus(notes.length ? 'Timestamp notes are up to date.' : 'No notes yet. Add one at the current playback position.', notes.length ? 'success' : '')
      renderNotes()
      syncControls()
    } catch (error) {
      if (serial !== state.requestSerial) return
      state.courseId = courseId
      state.itemId = ''
      state.notes = []
      setStatus(error instanceof Error ? error.message : 'Unable to load timestamp notes.', 'error')
      renderNotes()
      syncControls()
    }
  }

  async function saveNote() {
    const itemId = publicId(state.itemId)
    const textarea = $('learningNoteBody')
    const body = String(textarea?.value || '').trim()
    if (!itemId) {
      setStatus('Select an active lecture before adding a note.', 'error')
      return
    }
    if (!body) {
      setStatus('Note text is required.', 'error')
      textarea?.focus()
      return
    }
    if (body.length > 20000) {
      setStatus('Note is too long.', 'error')
      textarea?.focus()
      return
    }

    state.loading = true
    syncControls()
    setStatus('Saving timestamp note…')
    const timestampSeconds = activeSeconds()
    try {
      const payload = await api(`/v1/learning/items/${encodeURIComponent(itemId)}/notes`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ timestampSeconds, body }),
      })
      if (itemId !== state.itemId) return
      const note = payload?.note && typeof payload.note === 'object' ? payload.note : null
      if (!note || !publicId(note.id)) throw new Error('Saved note response is invalid')
      if (textarea) textarea.value = ''
      state.notes = await loadNotesForItem(itemId)
      setStatus(`Saved note at ${formatTime(note.timestampSeconds)}.`, 'success')
      renderNotes()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to save timestamp note.', 'error')
    } finally {
      state.loading = false
      syncControls()
    }
  }

  async function deleteNote(noteIdValue) {
    const noteId = publicId(noteIdValue)
    const itemId = publicId(state.itemId)
    if (!noteId || !itemId || state.loading) return
    state.loading = true
    syncControls()
    setStatus('Deleting timestamp note…')
    try {
      const payload = await api(`/v1/learning/notes/${encodeURIComponent(noteId)}/delete`, { method: 'POST' })
      if (publicId(payload?.noteId) !== noteId || payload?.deleted !== true) throw new Error('Delete note response is invalid')
      if (itemId !== state.itemId) return
      state.notes = await loadNotesForItem(itemId)
      setStatus('Timestamp note deleted.', 'success')
      renderNotes()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to delete timestamp note.', 'error')
    } finally {
      state.loading = false
      syncControls()
    }
  }

  function seekToNote(rawSeconds) {
    const seconds = safeSeconds(rawSeconds)
    const media = document.querySelector('.learning-player-media')
    if (!(media instanceof HTMLMediaElement)) {
      setStatus('Start local playback before jumping to a timestamp.', 'error')
      return
    }
    const ceiling = Number.isFinite(media.duration) && media.duration > 0 ? Math.max(0, media.duration - 0.25) : seconds
    media.currentTime = Math.min(seconds, ceiling)
    setStatus(`Jumped to ${formatTime(seconds)}.`, 'success')
    updateTimestampPreview()
    try { media.focus({ preventScroll: true }) } catch (_) {}
  }

  function scheduleRefresh(delay = 100) {
    window.clearTimeout(state.refreshTimer)
    state.refreshTimer = window.setTimeout(() => { void refreshCurrent() }, delay)
  }

  function observeLearning() {
    const detail = $('learningCourseDetail')
    if (!detail || state.observer) return
    state.observer = new MutationObserver((records) => {
      const meaningful = records.some((record) => {
        if (record.type === 'attributes') return record.attributeName === 'class'
        if (record.target instanceof Element && record.target.closest('#learningSections')) return true
        return Array.from(record.addedNodes).some((node) => node instanceof Element && (node.matches('.learning-player-media') || node.querySelector?.('.learning-player-media')))
      })
      if (meaningful) scheduleRefresh(120)
      updateTimestampPreview()
    })
    state.observer.observe(detail, { childList: true, subtree: true, attributes: true, attributeFilter: ['class'] })
  }

  document.addEventListener('DOMContentLoaded', () => {
    installPanel()
    observeLearning()
    scheduleRefresh(140)
  })

  document.addEventListener('timeupdate', (event) => {
    if (event.target instanceof HTMLMediaElement && event.target.matches('.learning-player-media')) updateTimestampPreview()
  }, true)

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return
    if (target.closest('[data-learning-course]')) scheduleRefresh(160)
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(state.refreshTimer)
    state.observer?.disconnect()
  })
})()
