(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const state = {
    observer: null,
    applyTimer: 0,
  }

  function normalize(value) {
    return String(value || '').trim().toLocaleLowerCase()
  }

  function installSearch() {
    const detail = $('learningCourseDetail')
    if (!detail || $('learningCourseSearch')) return

    const wrap = document.createElement('section')
    wrap.id = 'learningCourseSearch'
    wrap.className = 'learning-course-search'
    wrap.setAttribute('aria-labelledby', 'learningCourseSearchLabel')

    const label = document.createElement('label')
    label.id = 'learningCourseSearchLabel'
    label.htmlFor = 'learningCourseSearchInput'
    label.textContent = 'Search this course'

    const controls = document.createElement('div')
    controls.className = 'learning-course-search-controls'

    const input = document.createElement('input')
    input.id = 'learningCourseSearchInput'
    input.type = 'search'
    input.autocomplete = 'off'
    input.spellcheck = false
    input.maxLength = 240
    input.placeholder = 'Search section or lecture title…'
    input.setAttribute('aria-describedby', 'learningCourseSearchStatus')

    const clear = document.createElement('button')
    clear.id = 'learningCourseSearchClear'
    clear.className = 'button secondary'
    clear.type = 'button'
    clear.textContent = 'Clear'
    clear.disabled = true

    controls.append(input, clear)

    const status = document.createElement('div')
    status.id = 'learningCourseSearchStatus'
    status.className = 'learning-course-search-status'
    status.setAttribute('role', 'status')
    status.setAttribute('aria-live', 'polite')
    status.textContent = 'Search section and lecture titles.'

    const empty = document.createElement('div')
    empty.id = 'learningCourseSearchEmpty'
    empty.className = 'learning-course-search-empty is-hidden'
    empty.textContent = 'No matching lectures.'

    wrap.append(label, controls, status, empty)

    const notes = $('learningNotesPanel')
    const sections = $('learningSections')
    if (notes && notes.parentNode === detail) detail.insertBefore(wrap, notes)
    else if (sections && sections.parentNode === detail) detail.insertBefore(wrap, sections)
    else detail.appendChild(wrap)

    input.addEventListener('input', () => scheduleApply(40))
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && input.value) {
        event.preventDefault()
        input.value = ''
        applySearch()
      }
    })
    clear.addEventListener('click', () => {
      input.value = ''
      applySearch()
      input.focus()
    })
  }

  function sectionTitle(section) {
    return normalize(section.querySelector('.learning-section-head strong')?.textContent)
  }

  function lectureTitle(lecture) {
    return normalize(lecture.querySelector('strong')?.textContent)
  }

  function applySearch() {
    installSearch()
    const input = $('learningCourseSearchInput')
    const clear = $('learningCourseSearchClear')
    const status = $('learningCourseSearchStatus')
    const empty = $('learningCourseSearchEmpty')
    const sectionsRoot = $('learningSections')
    if (!input || !clear || !status || !empty || !sectionsRoot) return

    const query = normalize(input.value)
    clear.disabled = !query

    const sections = Array.from(sectionsRoot.querySelectorAll('.learning-section'))
    let totalLectures = 0
    let matchedLectures = 0
    let matchedSections = 0

    for (const section of sections) {
      const lectures = Array.from(section.querySelectorAll('.learning-lecture'))
      totalLectures += lectures.length
      const sectionMatches = Boolean(query) && sectionTitle(section).includes(query)
      let sectionLectureMatches = 0

      for (const lecture of lectures) {
        const matches = !query || sectionMatches || lectureTitle(lecture).includes(query)
        lecture.hidden = !matches
        if (matches) sectionLectureMatches += 1
      }

      const showSection = !query || sectionMatches || sectionLectureMatches > 0
      section.hidden = !showSection
      if (query && showSection) matchedSections += 1
      if (query) matchedLectures += sectionLectureMatches
    }

    const directLectures = Array.from(sectionsRoot.children)
      .filter((node) => node instanceof Element && node.matches('.learning-lecture'))
    for (const lecture of directLectures) {
      totalLectures += 1
      const matches = !query || lectureTitle(lecture).includes(query)
      lecture.hidden = !matches
      if (query && matches) matchedLectures += 1
    }

    if (!query) {
      empty.classList.add('is-hidden')
      status.textContent = totalLectures
        ? `${totalLectures} lecture${totalLectures === 1 ? '' : 's'} available.`
        : 'Search section and lecture titles.'
      return
    }

    const hasMatches = matchedLectures > 0
    empty.classList.toggle('is-hidden', hasMatches)
    status.textContent = hasMatches
      ? `${matchedLectures} matching lecture${matchedLectures === 1 ? '' : 's'} in ${matchedSections || 1} section${matchedSections === 1 ? '' : 's'}.`
      : `No lectures match “${input.value.trim()}”.`
  }

  function scheduleApply(delay = 60) {
    window.clearTimeout(state.applyTimer)
    state.applyTimer = window.setTimeout(applySearch, delay)
  }

  function observeSections() {
    const root = $('learningSections')
    if (!root || state.observer) return
    state.observer = new MutationObserver(() => scheduleApply(20))
    state.observer.observe(root, { childList: true, subtree: true, characterData: true })
  }

  document.addEventListener('DOMContentLoaded', () => {
    installSearch()
    observeSections()
    scheduleApply(120)
  })

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return
    if (target.closest('[data-learning-course]')) scheduleApply(180)
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(state.applyTimer)
    state.observer?.disconnect()
  })
})()
