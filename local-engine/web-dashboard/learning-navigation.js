(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const idPattern = /^[a-f0-9]{32}$/
  const languagePattern = /^[A-Za-z0-9][A-Za-z0-9._-]{0,31}$/
  const state = {
    courseId: '',
    items: [],
    sections: [],
    selectedItemId: '',
    refreshTimer: 0,
    observer: null,
  }

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  }

  async function api(path) {
    const response = await fetch(path, { headers: authHeaders(), cache: 'no-store' })
    if (response.status === 401) throw new Error('Headless API requires a valid Bearer token')
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    return response.json().catch(() => ({}))
  }

  function selectedCourseId() {
    return String(document.querySelector('[data-learning-course].is-selected')?.dataset.learningCourse || '')
  }

  function publicItemId(value) {
    const clean = String(value || '').trim().toLowerCase()
    return idPattern.test(clean) ? clean : ''
  }

  function subtitleTracks(item) {
    const tracks = Array.isArray(item?.subtitleTracks) ? item.subtitleTracks.slice(0, 64) : []
    const seen = new Set()
    const rows = []
    for (const track of tracks) {
      if (!track || typeof track !== 'object') continue
      const language = String(track.language || '').trim()
      const kind = String(track.kind || '').trim().toLowerCase()
      if (!languagePattern.test(language) || !['manual', 'automatic'].includes(kind)) continue
      const key = `${language}\u0000${kind}`
      if (seen.has(key)) continue
      seen.add(key)
      rows.push({ language, kind })
    }
    return rows
  }

  function installPanel() {
    const detail = $('learningCourseDetail')
    if (!detail || $('learningNavigationPanel')) return
    const panel = document.createElement('section')
    panel.id = 'learningNavigationPanel'
    panel.className = 'learning-navigation-panel'
    panel.innerHTML = `
      <div class="learning-navigation-head">
        <div><h3>Chapter navigation & subtitles</h3><p>Jump by chapter or lecture. Only subtitle language and Manual/Auto type are displayed.</p></div>
        <button class="button secondary" id="learningNavigationRefresh" type="button">Refresh</button>
      </div>
      <div id="learningNavigationNotice" class="learning-navigation-notice is-hidden" aria-live="polite"></div>
      <div id="learningChapterNav" class="learning-chapter-nav"></div>
      <div class="learning-lecture-navigator">
        <label class="field"><span>Lecture</span><select id="learningNavigationLecture"></select></label>
        <div class="learning-navigation-actions">
          <button class="button secondary" id="learningNavigationPrevious" type="button">← Previous</button>
          <button class="button secondary" id="learningNavigationNext" type="button">Next →</button>
        </div>
      </div>
      <div id="learningSubtitleSummary" class="learning-subtitle-summary"><span>No lecture selected.</span></div>`
    detail.appendChild(panel)
    $('learningNavigationRefresh')?.addEventListener('click', () => refreshCurrent())
    $('learningNavigationLecture')?.addEventListener('change', (event) => {
      state.selectedItemId = publicItemId(event.target.value)
      renderSelection()
    })
    $('learningNavigationPrevious')?.addEventListener('click', () => move('previousItemId'))
    $('learningNavigationNext')?.addEventListener('click', () => move('nextItemId'))
  }

  function notice(message) {
    const node = $('learningNavigationNotice')
    if (!node) return
    node.textContent = message || ''
    node.classList.toggle('is-hidden', !message)
  }

  function safeOrderIndex(value) {
    const parsed = Number(value)
    return Number.isInteger(parsed) && parsed >= 0 ? parsed : Number.MAX_SAFE_INTEGER
  }

  function orderedItems(items) {
    return [...items].sort((a, b) => {
      const ai = safeOrderIndex(a?.courseItemIndex)
      const bi = safeOrderIndex(b?.courseItemIndex)
      return ai - bi || String(a?.id || '').localeCompare(String(b?.id || ''))
    })
  }

  function renderChapters() {
    const node = $('learningChapterNav')
    if (!node) return
    const bySection = new Map()
    for (const item of state.items) {
      const sectionId = String(item?.sectionId || '')
      if (!bySection.has(sectionId)) bySection.set(sectionId, [])
      bySection.get(sectionId).push(item)
    }
    const buttons = []
    const sections = [...state.sections].sort((a, b) => (Number(a?.position) || 0) - (Number(b?.position) || 0))
    for (const [index, section] of sections.entries()) {
      const sectionId = String(section?.id || '')
      const items = orderedItems(bySection.get(sectionId) || [])
      const firstId = publicItemId(items[0]?.id)
      const total = Math.max(0, Number(section?.itemCount) || items.length)
      const completed = Math.max(0, Math.min(Number(section?.completedCount) || 0, total))
      const label = `${index + 1}. ${String(section?.title || 'Section')} · ${completed}/${total}`
      buttons.push(`<button class="learning-chapter-button" type="button" data-learning-chapter-first="${esc(firstId)}" ${firstId ? '' : 'disabled'}>${esc(label)}</button>`)
      bySection.delete(sectionId)
    }
    const unsectioned = orderedItems([...(bySection.get('') || []), ...[...bySection.entries()].filter(([key]) => key).flatMap(([, rows]) => rows)])
    const firstUnsectioned = publicItemId(unsectioned[0]?.id)
    if (unsectioned.length) {
      buttons.push(`<button class="learning-chapter-button" type="button" data-learning-chapter-first="${esc(firstUnsectioned)}">Unsectioned · ${unsectioned.length}</button>`)
    }
    node.innerHTML = buttons.join('') || '<span class="empty compact-empty">No chapters available.</span>'
  }

  function renderLectureOptions() {
    const select = $('learningNavigationLecture')
    if (!select) return
    const items = orderedItems(state.items).filter((item) => publicItemId(item?.id))
    select.innerHTML = items.map((item, index) => `<option value="${esc(publicItemId(item.id))}">${esc(`${index + 1}. ${String(item.title || item.fileName || 'Lecture')}`)}</option>`).join('')
    if (!items.length) {
      state.selectedItemId = ''
      select.innerHTML = '<option value="">No lectures</option>'
      return
    }
    if (!items.some((item) => publicItemId(item.id) === state.selectedItemId)) {
      state.selectedItemId = publicItemId(items[0].id)
    }
    select.value = state.selectedItemId
  }

  function currentItem() {
    return state.items.find((item) => publicItemId(item?.id) === state.selectedItemId) || null
  }

  function renderSelection() {
    const item = currentItem()
    const previous = $('learningNavigationPrevious')
    const next = $('learningNavigationNext')
    const summary = $('learningSubtitleSummary')
    if (!item) {
      if (previous) previous.disabled = true
      if (next) next.disabled = true
      if (summary) summary.innerHTML = '<span>No lecture selected.</span>'
      return
    }
    const previousId = publicItemId(item.previousItemId)
    const nextId = publicItemId(item.nextItemId)
    if (previous) previous.disabled = !previousId || !state.items.some((row) => publicItemId(row?.id) === previousId)
    if (next) next.disabled = !nextId || !state.items.some((row) => publicItemId(row?.id) === nextId)
    if (!summary) return
    const tracks = subtitleTracks(item)
    summary.innerHTML = tracks.length
      ? `<strong>${esc(String(item.title || item.fileName || 'Lecture'))}</strong><div class="learning-subtitle-badges">${tracks.map((track) => `<span class="learning-subtitle-badge"><b>${esc(track.language)}</b> ${track.kind === 'manual' ? 'Manual' : 'Auto'}</span>`).join('')}</div>`
      : `<strong>${esc(String(item.title || item.fileName || 'Lecture'))}</strong><span>No subtitle tracks.</span>`
  }

  function render(payload) {
    state.sections = Array.isArray(payload?.sections) ? payload.sections.filter((row) => row && typeof row === 'object') : []
    state.items = Array.isArray(payload?.items) ? payload.items.filter((row) => row && typeof row === 'object') : []
    renderChapters()
    renderLectureOptions()
    renderSelection()
  }

  function move(field) {
    const item = currentItem()
    if (!item) return
    const target = publicItemId(item[field])
    if (!target || !state.items.some((row) => publicItemId(row?.id) === target)) return
    state.selectedItemId = target
    const select = $('learningNavigationLecture')
    if (select) select.value = target
    renderSelection()
  }

  async function refreshCurrent() {
    installPanel()
    const courseId = selectedCourseId()
    if (!courseId) {
      state.courseId = ''
      state.items = []
      state.sections = []
      state.selectedItemId = ''
      render({ sections: [], items: [] })
      return
    }
    try {
      const payload = await api(`/v1/learning/courses/${encodeURIComponent(courseId)}?itemLimit=2000`)
      if (courseId !== selectedCourseId()) return
      if (courseId !== state.courseId) state.selectedItemId = ''
      state.courseId = courseId
      render(payload)
      notice('')
    } catch (error) {
      notice(error instanceof Error ? error.message : 'Unable to load chapter navigation')
    }
  }

  function scheduleRefresh(delay = 70) {
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
    const chapter = target.closest('[data-learning-chapter-first]')
    if (chapter) {
      const first = publicItemId(chapter.dataset.learningChapterFirst)
      if (first) {
        state.selectedItemId = first
        const select = $('learningNavigationLecture')
        if (select) select.value = first
        renderSelection()
      }
      return
    }
    if (target.closest('[data-learning-course]')) scheduleRefresh(130)
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(state.refreshTimer)
    state.observer?.disconnect()
  })
})()
