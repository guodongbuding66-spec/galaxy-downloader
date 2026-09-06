(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const terminalStates = new Set(['completed', 'failed', 'cancelled'])
  const jobs = new Map()
  const pollTimers = new Map()
  let refreshTimer = 0
  let observer = null

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  }

  async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: authHeaders(options.headers || {}), cache: 'no-store' })
    if (response.status === 401) throw new Error('Headless API requires a valid Bearer token')
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(`Request failed (${response.status})`)
    return payload
  }

  function postJson(path, payload = {}) {
    return api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  }

  function formatBytes(value) {
    let size = Number(value) || 0
    if (!Number.isFinite(size) || size <= 0) return '—'
    const units = ['B', 'KB', 'MB', 'GB']
    let index = 0
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024
      index += 1
    }
    return index === 0 ? `${Math.round(size)} B` : `${size.toFixed(1)} ${units[index]}`
  }

  function selectedCourseId() {
    return String(document.querySelector('[data-learning-course].is-selected')?.dataset.learningCourse || '')
  }

  function browserSource() {
    return String($('learningBrowser')?.value || 'none')
  }

  function installPanel() {
    const detail = $('learningCourseDetail')
    if (!detail || $('learningAttachmentPanel')) return
    const panel = document.createElement('section')
    panel.id = 'learningAttachmentPanel'
    panel.className = 'learning-attachment-panel'
    panel.innerHTML = `
      <div class="learning-attachment-head">
        <div><h3>Course attachments</h3><p>Authorized lecture files use the selected browser login. Signed URLs and local paths are never shown.</p></div>
        <button class="button secondary" id="learningAttachmentRefresh" type="button">Refresh attachments</button>
      </div>
      <div id="learningAttachmentNotice" class="learning-attachment-notice is-hidden" aria-live="polite"></div>
      <div id="learningAttachmentList" class="learning-attachment-list"><div class="empty compact-empty">No course selected.</div></div>`
    detail.appendChild(panel)
  }

  function jobLabel(job) {
    const state = String(job?.state || '')
    const progress = Math.max(0, Math.min(Number(job?.progress) || 0, 100))
    if (state === 'queued') return `Queued · ${Math.round(progress)}%`
    if (state === 'running') return `Downloading · ${Math.round(progress)}%`
    if (state === 'cancelling') return 'Cancelling'
    if (state === 'completed') return 'Downloaded'
    if (state === 'cancelled') return 'Cancelled'
    if (state === 'failed') return 'Download failed'
    return ''
  }

  function attachmentRow(attachment, lectureTitle) {
    const id = String(attachment.id || '')
    const job = jobs.get(id) || null
    const jobState = String(job?.state || '')
    const running = job && !terminalStates.has(jobState)
    const downloaded = Boolean(attachment.downloaded) || jobState === 'completed'
    const title = attachment.title || attachment.fileName || 'Attachment'
    const meta = [attachment.assetType || '', attachment.fileName || '', formatBytes(attachment.sizeBytes || job?.sizeBytes)].filter(Boolean).join(' · ')
    const status = job ? jobLabel(job) : downloaded ? 'Downloaded' : 'Not downloaded'
    const action = running
      ? `<button class="button secondary danger-button" data-learning-attachment-cancel="${esc(id)}" type="button">Cancel</button>`
      : downloaded
        ? '<span class="learning-attachment-done">✓ Downloaded</span>'
        : `<button class="button secondary" data-learning-attachment-download="${esc(id)}" type="button">Download</button>`
    return `<article class="learning-attachment-row"><div class="learning-attachment-copy"><strong>${esc(title)}</strong><span>${esc(lectureTitle)}</span><small>${esc(meta || 'Course attachment')}</small></div><div class="learning-attachment-state"><span>${esc(status)}</span>${action}</div></article>`
  }

  function render(detail) {
    const list = $('learningAttachmentList')
    if (!list) return
    const items = Array.isArray(detail?.items) ? detail.items : []
    const blocks = []
    for (const item of items) {
      const attachments = Array.isArray(item?.attachments) ? item.attachments : []
      for (const attachment of attachments) {
        if (!attachment || typeof attachment !== 'object' || !attachment.id) continue
        blocks.push(attachmentRow(attachment, String(item.title || item.fileName || 'Lecture')))
      }
    }
    list.innerHTML = blocks.join('') || '<div class="empty compact-empty">This course has no downloadable attachments.</div>'
  }

  function notice(message) {
    const node = $('learningAttachmentNotice')
    if (!node) return
    node.textContent = message || ''
    node.classList.toggle('is-hidden', !message)
  }

  async function refreshCurrent() {
    installPanel()
    const courseId = selectedCourseId()
    if (!courseId) {
      const list = $('learningAttachmentList')
      if (list) list.innerHTML = '<div class="empty compact-empty">Select a course to inspect attachments.</div>'
      return
    }
    try {
      const detail = await api(`/v1/learning/courses/${encodeURIComponent(courseId)}?itemLimit=2000`)
      if (courseId !== selectedCourseId()) return
      render(detail)
      notice('')
    } catch (error) {
      notice(error instanceof Error ? error.message : 'Unable to load course attachments')
    }
  }

  function scheduleRefresh(delay = 60) {
    window.clearTimeout(refreshTimer)
    refreshTimer = window.setTimeout(refreshCurrent, delay)
  }

  function stopJobPolling(attachmentId) {
    const timer = pollTimers.get(attachmentId)
    if (timer) window.clearTimeout(timer)
    pollTimers.delete(attachmentId)
  }

  async function pollJob(attachmentId) {
    stopJobPolling(attachmentId)
    const current = jobs.get(attachmentId)
    const jobId = String(current?.id || '')
    if (!jobId) return
    try {
      const payload = await api(`/v1/learning/attachments/downloads/${encodeURIComponent(jobId)}`)
      const job = payload.job || {}
      jobs.set(attachmentId, job)
      await refreshCurrent()
      const state = String(job.state || '')
      if (!terminalStates.has(state)) {
        pollTimers.set(attachmentId, window.setTimeout(() => pollJob(attachmentId), 900))
      } else if (state === 'completed') {
        jobs.delete(attachmentId)
        await refreshCurrent()
      }
    } catch (error) {
      notice(error instanceof Error ? error.message : 'Unable to refresh attachment download')
    }
  }

  async function startDownload(attachmentId) {
    const result = await postJson('/v1/learning/attachments/download', {
      attachmentId,
      browser: browserSource(),
    })
    const job = result.job || {}
    if (!job.id) throw new Error('Attachment download job was not created')
    jobs.set(attachmentId, job)
    await refreshCurrent()
    pollTimers.set(attachmentId, window.setTimeout(() => pollJob(attachmentId), 350))
  }

  async function cancelDownload(attachmentId) {
    const job = jobs.get(attachmentId)
    const jobId = String(job?.id || '')
    if (!jobId) return
    const result = await postJson(`/v1/learning/attachments/downloads/${encodeURIComponent(jobId)}/cancel`)
    jobs.set(attachmentId, result.job || job)
    await refreshCurrent()
    if (!terminalStates.has(String(result.job?.state || ''))) {
      pollTimers.set(attachmentId, window.setTimeout(() => pollJob(attachmentId), 350))
    }
  }

  function observeLearning() {
    const sections = $('learningSections')
    if (!sections || observer) return
    observer = new MutationObserver(() => scheduleRefresh())
    observer.observe(sections, { childList: true, subtree: true })
  }

  document.addEventListener('DOMContentLoaded', () => {
    installPanel()
    observeLearning()
    $('learningAttachmentRefresh')?.addEventListener('click', () => refreshCurrent())
  })

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return
    const download = target.closest('[data-learning-attachment-download]')
    if (download) {
      const id = String(download.dataset.learningAttachmentDownload || '')
      startDownload(id).catch((error) => notice(error instanceof Error ? error.message : 'Attachment download failed'))
      return
    }
    const cancel = target.closest('[data-learning-attachment-cancel]')
    if (cancel) {
      const id = String(cancel.dataset.learningAttachmentCancel || '')
      cancelDownload(id).catch((error) => notice(error instanceof Error ? error.message : 'Unable to cancel attachment download'))
      return
    }
    if (target.closest('[data-learning-course]')) scheduleRefresh(120)
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(refreshTimer)
    for (const timer of pollTimers.values()) window.clearTimeout(timer)
    pollTimers.clear()
    observer?.disconnect()
  })
})()
