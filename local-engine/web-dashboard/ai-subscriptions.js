(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const state = {
    providers: [],
    prompts: [],
    queue: { active: [], waiting: [], activeCount: 0, waitingCount: 0 },
    history: [],
    media: [],
    subscriptions: [],
    selectedSubscriptionId: '',
    selectedSubscriptionDetail: null,
    subscriptionItems: [],
  }
  const subscriptionTransitions = {
    waiting: ['approved', 'skipped'],
    approved: ['queued', 'skipped', 'waiting'],
    queued: ['downloading', 'completed', 'failed', 'approved', 'waiting', 'skipped'],
    downloading: ['completed', 'failed', 'approved', 'waiting'],
    completed: [],
    failed: ['approved', 'waiting', 'skipped'],
    skipped: ['approved', 'waiting'],
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

  function formatDate(value) {
    if (value === null || value === undefined || value === '') return '—'
    const numeric = Number(value)
    const date = Number.isFinite(numeric) && String(value).trim() !== '' ? new Date(numeric * 1000) : new Date(value)
    return Number.isNaN(date.getTime()) ? '—' : new Intl.DateTimeFormat(undefined, { month: 'short', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date)
  }

  function listTerms(value) {
    return String(value || '').split(',').map((item) => item.trim()).filter(Boolean).slice(0, 30)
  }

  function hideCoreViews() {
    for (const id of ['dashboardView', 'downloadsView', 'libraryView', 'transcriptView']) $(id)?.classList.add('is-hidden')
  }

  function closeOpsViews() {
    $('aiView')?.classList.add('is-hidden')
    $('subscriptionsView')?.classList.add('is-hidden')
    document.querySelectorAll('[data-ops-view]').forEach((button) => button.classList.remove('is-active'))
  }

  function showOpsView(name) {
    hideCoreViews()
    closeOpsViews()
    document.querySelectorAll('[data-view]').forEach((button) => button.classList.remove('is-active'))
    const view = name === 'subscriptions' ? 'subscriptions' : 'ai'
    $(`${view}View`).classList.remove('is-hidden')
    document.querySelector(`[data-ops-view="${view}"]`)?.classList.add('is-active')
    $('viewTitle').textContent = view === 'ai' ? 'AI' : 'Subscriptions'
    if (view === 'ai') loadAI()
    else loadSubscriptions()
  }

  function providerLabel(provider) {
    const status = provider.enabled ? (provider.hasApiKey || provider.allowLocal ? 'ready' : 'credential missing') : 'disabled'
    return `${provider.name || provider.id} · ${status}`
  }

  function renderAISelectors() {
    $('aiTaskProvider').innerHTML = state.providers.length ? state.providers.map((provider) => `<option value="${esc(provider.id)}">${esc(providerLabel(provider))}</option>`).join('') : '<option value="">No providers</option>'
    $('aiTaskPrompt').innerHTML = '<option value="">Raw instructions</option>' + state.prompts.map((prompt) => `<option value="${esc(prompt.id)}">${esc(prompt.title || prompt.id)}</option>`).join('')
    $('aiTaskMedia').innerHTML = '<option value="">Text task</option>' + state.media.map((item) => `<option value="${esc(item.id)}">${esc(item.title || item.fileName || item.id)}</option>`).join('')
  }

  function renderAIProviders() {
    $('aiProviderCount').textContent = String(state.providers.length)
    const ready = state.providers.filter((provider) => provider.enabled && (provider.hasApiKey || provider.allowLocal)).length
    $('aiProviderReady').textContent = `${ready} ready`
    $('aiProviderList').innerHTML = state.providers.length ? state.providers.map((provider) => `<article class="ops-row"><div class="ops-row-main"><strong>${esc(provider.name || provider.id)}</strong><span>${esc(provider.id)} · ${esc(provider.protocol || '')} · ${esc(provider.model || 'model not set')}</span><span>${esc(provider.baseUrl || 'endpoint not set')}</span></div><div class="ops-row-meta"><span class="ops-status ${provider.enabled ? 'ok' : 'muted-status'}">${provider.enabled ? 'Enabled' : 'Disabled'}</span><span class="ops-status ${provider.hasApiKey || provider.allowLocal ? 'ok' : 'warn'}">${provider.hasApiKey ? 'Credential ready' : provider.allowLocal ? 'Local' : 'No credential'}</span></div><div class="ops-row-actions"><button class="action" data-ai-provider-edit="${esc(provider.id)}" type="button">Edit</button>${provider.custom ? `<button class="action danger-text" data-ai-provider-delete="${esc(provider.id)}" type="button">Delete</button>` : `<button class="action" data-ai-provider-reset="${esc(provider.id)}" type="button">Reset</button>`}</div></article>`).join('') : '<div class="empty">No providers configured.</div>'
  }

  function renderAIPrompts() {
    $('aiPromptCount').textContent = String(state.prompts.length)
    $('aiPromptList').innerHTML = state.prompts.length ? state.prompts.map((prompt) => `<article class="ops-row"><div class="ops-row-main"><strong>${esc(prompt.title || prompt.id)}</strong><span>${esc(prompt.id)} · ${prompt.builtin ? 'built-in' : 'custom'}</span><span class="line-clamp">${esc(prompt.instructions || '')}</span></div><div class="ops-row-actions"><button class="action" data-ai-prompt-edit="${esc(prompt.id)}" type="button">Edit</button><button class="action" data-ai-prompt-duplicate="${esc(prompt.id)}" type="button">Duplicate</button><button class="action ${prompt.builtin ? '' : 'danger-text'}" data-ai-prompt-delete="${esc(prompt.id)}" type="button">${prompt.builtin ? 'Reset' : 'Delete'}</button></div></article>`).join('') : '<div class="empty">No prompts available.</div>'
  }

  function aiTaskRow(task, waiting = false) {
    const canCancel = ['queued', 'running', 'cancelling'].includes(String(task.state || ''))
    return `<article class="ops-row compact"><div class="ops-row-main"><strong>${esc(task.label || task.id)}</strong><span>${esc(task.providerId || '')}${task.promptId ? ` · ${esc(task.promptId)}` : ''}${waiting && task.position ? ` · position ${esc(task.position)}` : ''}</span></div><div class="ops-row-meta"><span class="ops-status">${esc(task.state || 'unknown')}</span></div><div class="ops-row-actions">${canCancel ? `<button class="action danger-text" data-ai-task-cancel="${esc(task.id)}" type="button">Cancel</button>` : ''}</div></article>`
  }

  function renderAIQueue() {
    const active = Array.isArray(state.queue.active) ? state.queue.active : []
    const waiting = Array.isArray(state.queue.waiting) ? state.queue.waiting : []
    $('aiActiveCount').textContent = String(Number(state.queue.activeCount) || active.length)
    $('aiWaitingCount').textContent = String(Number(state.queue.waitingCount) || waiting.length)
    $('aiQueueMeta').textContent = `${active.length} active · ${waiting.length} waiting`
    $('aiQueueList').innerHTML = [...active.map((task) => aiTaskRow(task)), ...waiting.map((task) => aiTaskRow(task, true))].join('') || '<div class="empty">No AI tasks.</div>'
  }

  function renderAIHistory() {
    $('aiHistoryCount').textContent = String(state.history.length)
    $('aiHistoryMeta').textContent = `${state.history.length} recent run${state.history.length === 1 ? '' : 's'}`
    $('aiHistoryList').innerHTML = state.history.length ? state.history.map((run) => `<article class="ops-row"><div class="ops-row-main"><strong>${esc(run.promptId || run.model || run.providerId || 'AI run')}</strong><span>${esc(run.providerId || '')} · ${esc(run.status || '')} · ${esc(formatDate(run.createdAt))}</span><span class="line-clamp">${esc(run.resultPreview || run.errorDetail || '')}</span></div><div class="ops-row-meta"><span class="ops-status ${run.status === 'succeeded' ? 'ok' : run.status === 'failed' ? 'bad' : ''}">${esc(run.status || 'unknown')}</span><span class="numeric">${Number(run.durationMs) ? `${Math.round(Number(run.durationMs))} ms` : '—'}</span></div><div class="ops-row-actions"><button class="action" data-ai-history-detail="${esc(run.id)}" type="button">Detail</button><button class="action danger-text" data-ai-history-delete="${esc(run.id)}" type="button">Delete</button></div></article>`).join('') : '<div class="empty">No AI history.</div>'
  }

  async function loadAI() {
    try {
      const status = $('aiHistoryStatus').value
      const historyQuery = status ? `?status=${encodeURIComponent(status)}&limit=100` : '?limit=100'
      const [providers, prompts, queue, history, media] = await Promise.all([
        api('/v1/ai/providers'),
        api('/v1/ai/prompts'),
        api('/v1/ai/queue'),
        api(`/v1/ai/history${historyQuery}`),
        api('/v1/media?limit=100&offset=0'),
      ])
      state.providers = Array.isArray(providers.providers) ? providers.providers : []
      state.prompts = Array.isArray(prompts.prompts) ? prompts.prompts : []
      state.queue = queue
      state.history = Array.isArray(history.runs) ? history.runs : []
      state.media = Array.isArray(media.items) ? media.items : []
      renderAISelectors()
      renderAIProviders()
      renderAIPrompts()
      renderAIQueue()
      renderAIHistory()
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load AI workspace')
    }
  }

  function editProvider(providerId = '') {
    const provider = state.providers.find((item) => item.id === providerId)
    $('aiProviderForm').classList.remove('is-hidden')
    $('aiProviderOriginalId').value = provider?.id || ''
    $('aiProviderId').value = provider?.id || ''
    $('aiProviderId').disabled = Boolean(provider)
    $('aiProviderName').value = provider?.name || ''
    $('aiProviderProtocol').value = provider?.protocol || 'openai'
    $('aiProviderModel').value = provider?.model || ''
    $('aiProviderBaseUrl').value = provider?.baseUrl || ''
    $('aiProviderCredential').value = provider?.credentialReference || ''
    $('aiProviderTimeout').value = String(provider?.timeoutSeconds || 180)
    $('aiProviderEnabled').checked = provider ? Boolean(provider.enabled) : true
    $('aiProviderAllowLocal').checked = Boolean(provider?.allowLocal)
    $('aiProviderName').focus()
  }

  function closeProviderEditor() {
    $('aiProviderForm').classList.add('is-hidden')
    $('aiProviderId').disabled = false
  }

  async function saveProvider() {
    const payload = {
      id: $('aiProviderOriginalId').value || $('aiProviderId').value.trim(),
      name: $('aiProviderName').value.trim(),
      protocol: $('aiProviderProtocol').value,
      baseUrl: $('aiProviderBaseUrl').value.trim(),
      model: $('aiProviderModel').value.trim(),
      enabled: $('aiProviderEnabled').checked,
      allowLocal: $('aiProviderAllowLocal').checked,
      timeoutSeconds: Number($('aiProviderTimeout').value) || 180,
      credentialReference: $('aiProviderCredential').value.trim(),
    }
    await postJson('/v1/ai/providers', payload)
    closeProviderEditor()
    await loadAI()
  }

  function editPrompt(promptId = '') {
    const prompt = state.prompts.find((item) => item.id === promptId)
    $('aiPromptForm').classList.remove('is-hidden')
    $('aiPromptId').value = prompt?.id || ''
    $('aiPromptId').disabled = Boolean(prompt)
    $('aiPromptTitle').value = prompt?.title || ''
    $('aiPromptIcon').value = prompt?.icon || 'sparkles'
    $('aiPromptInstructions').value = prompt?.instructions || ''
    $('aiPromptTitle').focus()
  }

  function closePromptEditor() {
    $('aiPromptForm').classList.add('is-hidden')
    $('aiPromptId').disabled = false
  }

  async function savePrompt() {
    await postJson('/v1/ai/prompts', {
      id: $('aiPromptId').value.trim(),
      title: $('aiPromptTitle').value.trim(),
      icon: $('aiPromptIcon').value.trim() || 'sparkles',
      instructions: $('aiPromptInstructions').value.trim(),
    })
    closePromptEditor()
    await loadAI()
  }

  async function submitAITask() {
    const providerId = $('aiTaskProvider').value
    const promptId = $('aiTaskPrompt').value
    const mediaId = $('aiTaskMedia').value
    const instructions = $('aiTaskInstructions').value.trim()
    const base = {
      providerId,
      promptId,
      instructions,
      extraInstruction: $('aiTaskExtra').value.trim(),
      label: $('aiTaskLabel').value.trim(),
    }
    if (!providerId) throw new Error('Select an AI provider')
    if (!promptId && !instructions) throw new Error('Select a Prompt or provide raw instructions')
    if (mediaId) await postJson('/v1/ai/tasks/transcript', { ...base, mediaId })
    else {
      const content = $('aiTaskContent').value.trim()
      if (!content) throw new Error('Content is required for a text AI task')
      await postJson('/v1/ai/tasks/text', { ...base, content })
    }
    $('aiTaskContent').value = ''
    $('aiTaskExtra').value = ''
    $('aiTaskLabel').value = ''
    await loadAI()
  }

  async function showHistoryDetail(runId) {
    const result = await api(`/v1/ai/history/${encodeURIComponent(runId)}`)
    const run = result.run || {}
    const detail = $('aiHistoryDetail')
    detail.classList.remove('is-hidden')
    detail.innerHTML = `<div class="history-detail-header"><div><strong>${esc(run.promptId || run.model || run.providerId || 'AI run')}</strong><span>${esc(run.status || '')} · ${esc(formatDate(run.createdAt))}</span></div><button class="action" id="aiHistoryCloseDetail" type="button">Close</button></div><dl><div><dt>Provider</dt><dd>${esc(run.providerId || '—')}</dd></div><div><dt>Model</dt><dd>${esc(run.model || '—')}</dd></div><div><dt>Input</dt><dd>${esc(run.inputChars ?? 0)} chars</dd></div><div><dt>Output</dt><dd>${esc(run.outputChars ?? 0)} chars</dd></div><div><dt>Duration</dt><dd>${esc(run.durationMs ?? 0)} ms</dd></div></dl><pre>${esc(run.resultText || run.errorDetail || 'No result text')}</pre>`
    $('aiHistoryCloseDetail').addEventListener('click', () => detail.classList.add('is-hidden'), { once: true })
  }

  function renderSubscriptionSummary() {
    $('subsTotal').textContent = String(state.subscriptions.length)
    $('subsEnabled').textContent = String(state.subscriptions.filter((item) => item.enabled).length)
    $('subsAuto').textContent = String(state.subscriptions.filter((item) => item.autoDownload).length)
    $('subsErrors').textContent = String(state.subscriptions.filter((item) => item.lastError).length)
  }

  function renderSubscriptions() {
    renderSubscriptionSummary()
    $('subsList').innerHTML = state.subscriptions.length ? state.subscriptions.map((item) => `<button class="subscription-list-item ${item.id === state.selectedSubscriptionId ? 'is-selected' : ''}" data-subscription-select="${esc(item.id)}" type="button"><strong>${esc(item.title || item.sourceUrl || item.id)}</strong><span>${esc(item.sourceUrl || '')}</span><span>${item.enabled ? 'Enabled' : 'Disabled'} · ${esc(item.intervalMinutes)} min · ${esc(item.seenCount)} seen</span>${item.lastError ? `<em>${esc(item.lastError)}</em>` : ''}</button>`).join('') : '<div class="empty">No subscriptions.</div>'
  }

  async function loadSubscriptions() {
    try {
      const result = await api('/v1/subscriptions')
      state.subscriptions = Array.isArray(result.subscriptions) ? result.subscriptions : []
      if (state.selectedSubscriptionId && !state.subscriptions.some((item) => item.id === state.selectedSubscriptionId)) state.selectedSubscriptionId = ''
      renderSubscriptions()
      if (state.selectedSubscriptionId) await selectSubscription(state.selectedSubscriptionId)
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load subscriptions')
    }
  }

  function openSubscriptionEditor(subscription = null) {
    $('subsEmpty').classList.add('is-hidden')
    $('subsEditor').classList.remove('is-hidden')
    $('subsOperational').classList.toggle('is-hidden', !subscription)
    $('subsDeleteButton').classList.toggle('is-hidden', !subscription)
    $('subsId').value = subscription?.id || ''
    $('subsSourceUrl').value = subscription?.sourceUrl || ''
    $('subsTitle').value = subscription?.title || ''
    $('subsBrowser').value = subscription?.browser || 'none'
    $('subsInterval').value = String(subscription?.intervalMinutes || 60)
    $('subsVideoQuality').value = subscription?.videoQuality || 'best'
    $('subsAudioQuality').value = subscription?.audioQuality || 'best'
    $('subsEnabledField').checked = subscription ? Boolean(subscription.enabled) : true
    $('subsAutoField').checked = Boolean(subscription?.autoDownload)
    $('subsIncludeAudio').checked = subscription ? Boolean(subscription.includeAudio) : true
  }

  function closeSubscriptionEditor() {
    $('subsEditor').classList.add('is-hidden')
    $('subsEmpty').classList.remove('is-hidden')
    state.selectedSubscriptionId = ''
    state.selectedSubscriptionDetail = null
    state.subscriptionItems = []
    $('subsItemTotal').textContent = '0'
    renderSubscriptions()
  }

  function fillRules(rules = {}) {
    $('subsIncludeKeywords').value = Array.isArray(rules.includeKeywords) ? rules.includeKeywords.join(', ') : ''
    $('subsExcludeKeywords').value = Array.isArray(rules.excludeKeywords) ? rules.excludeKeywords.join(', ') : ''
    $('subsLatestN').value = String(Number(rules.latestN) || 0)
    $('subsTags').value = Array.isArray(rules.tags) ? rules.tags.join(', ') : ''
    $('subsProfile').value = rules.profile || ''
    $('subsFilename').value = rules.filename || ''
    $('subsManualReview').checked = Boolean(rules.manualReview)
    $('subsRulesAuto').checked = Boolean(rules.autoDownload)
  }

  function renderSubscriptionCounts(counts = {}) {
    const entries = Object.entries(counts).filter(([, value]) => Number.isFinite(Number(value)))
    const total = entries.reduce((sum, [, value]) => sum + Number(value || 0), 0)
    $('subsItemTotal').textContent = String(total)
    $('subsCountsMeta').textContent = entries.length ? entries.map(([key, value]) => `${key}: ${value}`).join(' · ') : 'No item counts loaded.'
  }

  function itemActionButtons(item) {
    const next = subscriptionTransitions[item.state] || []
    return next.slice(0, 6).map((target) => `<button class="mini-action" data-sub-item-id="${esc(item.entryId)}" data-sub-item-state="${esc(target)}" type="button">${esc(target)}</button>`).join('')
  }

  function renderSubscriptionItems() {
    $('subsItems').innerHTML = state.subscriptionItems.length ? state.subscriptionItems.map((item) => `<article class="ops-row"><div class="ops-row-main"><strong>${esc(item.title || item.entryId)}</strong><span>${esc(item.sourceHost || '')}${item.published ? ` · ${esc(item.published)}` : ''}</span><span>${esc(item.stateReason || item.lastError || '')}</span></div><div class="ops-row-meta"><span class="ops-status ${item.state === 'completed' ? 'ok' : item.state === 'failed' ? 'bad' : ''}">${esc(item.state || 'unknown')}</span><span>${item.present ? 'Present' : `Missing ×${esc(item.missingCount || 0)}`}</span></div><div class="ops-row-actions wrap-actions">${itemActionButtons(item)}</div></article>`).join('') : '<div class="empty">No subscription items match this filter.</div>'
  }

  async function loadSubscriptionItems(subscriptionId = state.selectedSubscriptionId) {
    if (!subscriptionId) return
    const itemState = $('subsItemState').value
    const query = new URLSearchParams({ limit: '500' })
    if (itemState) query.set('state', itemState)
    const result = await api(`/v1/subscriptions/${encodeURIComponent(subscriptionId)}/items?${query}`)
    state.subscriptionItems = Array.isArray(result.items) ? result.items : []
    renderSubscriptionItems()
  }

  async function selectSubscription(subscriptionId) {
    state.selectedSubscriptionId = String(subscriptionId || '')
    renderSubscriptions()
    try {
      const detail = await api(`/v1/subscriptions/${encodeURIComponent(state.selectedSubscriptionId)}`)
      state.selectedSubscriptionDetail = detail
      openSubscriptionEditor(detail.subscription || null)
      fillRules(detail.rules || {})
      renderSubscriptionCounts(detail.counts || {})
      await loadSubscriptionItems(state.selectedSubscriptionId)
      showError('')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load subscription')
    }
  }

  async function saveSubscription() {
    const id = $('subsId').value
    const payload = {
      sourceUrl: $('subsSourceUrl').value.trim(),
      title: $('subsTitle').value.trim(),
      browser: $('subsBrowser').value,
      enabled: $('subsEnabledField').checked,
      autoDownload: $('subsAutoField').checked,
      intervalMinutes: Number($('subsInterval').value) || 60,
      videoQuality: $('subsVideoQuality').value.trim() || 'best',
      audioQuality: $('subsAudioQuality').value.trim() || 'best',
      includeAudio: $('subsIncludeAudio').checked,
    }
    const result = id ? await postJson(`/v1/subscriptions/${encodeURIComponent(id)}/update`, payload) : await postJson('/v1/subscriptions', payload)
    state.selectedSubscriptionId = result.subscription?.id || id
    await loadSubscriptions()
  }

  async function saveSubscriptionRules() {
    if (!state.selectedSubscriptionId) return
    await postJson(`/v1/subscriptions/${encodeURIComponent(state.selectedSubscriptionId)}/rules`, {
      includeKeywords: listTerms($('subsIncludeKeywords').value),
      excludeKeywords: listTerms($('subsExcludeKeywords').value),
      latestN: Number($('subsLatestN').value) || 0,
      tags: listTerms($('subsTags').value),
      manualReview: $('subsManualReview').checked,
      autoDownload: $('subsRulesAuto').checked,
      profile: $('subsProfile').value.trim(),
      filename: $('subsFilename').value.trim(),
    })
    await selectSubscription(state.selectedSubscriptionId)
  }

  async function reconcileSubscription() {
    if (!state.selectedSubscriptionId) return
    const result = await postJson(`/v1/subscriptions/${encodeURIComponent(state.selectedSubscriptionId)}/reconcile`, { retryFailed: false, maxAttempts: 3 })
    $('subsCountsMeta').textContent = `Reconcile · missing ${Number(result.missing) || 0} · duplicates ${Number(result.duplicates) || 0} · recovered ${Number(result.recovered) || 0}`
    await selectSubscription(state.selectedSubscriptionId)
  }

  async function transitionSubscriptionItem(entryId, targetState) {
    if (!state.selectedSubscriptionId) return
    await postJson(`/v1/subscriptions/${encodeURIComponent(state.selectedSubscriptionId)}/items/transition`, { entryId, state: targetState, reason: 'web-dashboard' })
    await selectSubscription(state.selectedSubscriptionId)
  }

  document.addEventListener('click', async (event) => {
    const opsView = event.target.closest('[data-ops-view]')
    if (opsView) { showOpsView(opsView.dataset.opsView); return }
    const coreView = event.target.closest('[data-view], [data-view-jump]')
    if (coreView) closeOpsViews()

    try {
      const providerEdit = event.target.closest('[data-ai-provider-edit]')
      if (providerEdit) editProvider(providerEdit.dataset.aiProviderEdit)
      const providerReset = event.target.closest('[data-ai-provider-reset]')
      if (providerReset) { await postJson(`/v1/ai/providers/${encodeURIComponent(providerReset.dataset.aiProviderReset)}/reset`); await loadAI() }
      const providerDelete = event.target.closest('[data-ai-provider-delete]')
      if (providerDelete && window.confirm('Delete this custom AI provider?')) { await postJson(`/v1/ai/providers/${encodeURIComponent(providerDelete.dataset.aiProviderDelete)}/delete`); await loadAI() }

      const promptEdit = event.target.closest('[data-ai-prompt-edit]')
      if (promptEdit) editPrompt(promptEdit.dataset.aiPromptEdit)
      const promptDuplicate = event.target.closest('[data-ai-prompt-duplicate]')
      if (promptDuplicate) { await postJson(`/v1/ai/prompts/${encodeURIComponent(promptDuplicate.dataset.aiPromptDuplicate)}/duplicate`, {}); await loadAI() }
      const promptDelete = event.target.closest('[data-ai-prompt-delete]')
      if (promptDelete && window.confirm('Reset or delete this prompt?')) { await postJson(`/v1/ai/prompts/${encodeURIComponent(promptDelete.dataset.aiPromptDelete)}/delete`); await loadAI() }
      const taskCancel = event.target.closest('[data-ai-task-cancel]')
      if (taskCancel) { await postJson(`/v1/ai/tasks/${encodeURIComponent(taskCancel.dataset.aiTaskCancel)}/cancel`); await loadAI() }
      const historyDetail = event.target.closest('[data-ai-history-detail]')
      if (historyDetail) await showHistoryDetail(historyDetail.dataset.aiHistoryDetail)
      const historyDelete = event.target.closest('[data-ai-history-delete]')
      if (historyDelete && window.confirm('Delete this AI history run?')) { await postJson(`/v1/ai/history/${encodeURIComponent(historyDelete.dataset.aiHistoryDelete)}/delete`); await loadAI() }

      const subscriptionSelect = event.target.closest('[data-subscription-select]')
      if (subscriptionSelect) await selectSubscription(subscriptionSelect.dataset.subscriptionSelect)
      const transition = event.target.closest('[data-sub-item-state]')
      if (transition) await transitionSubscriptionItem(transition.dataset.subItemId, transition.dataset.subItemState)
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Operation failed')
    }
  })

  $('aiRefreshButton').addEventListener('click', loadAI)
  $('aiHistoryApplyButton').addEventListener('click', loadAI)
  $('aiProviderNewButton').addEventListener('click', () => editProvider())
  $('aiProviderCancelButton').addEventListener('click', closeProviderEditor)
  $('aiProviderForm').addEventListener('submit', async (event) => { event.preventDefault(); try { await saveProvider(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'Provider save failed') } })
  $('aiPromptNewButton').addEventListener('click', () => editPrompt())
  $('aiPromptCancelButton').addEventListener('click', closePromptEditor)
  $('aiPromptResetButton').addEventListener('click', async () => { try { await postJson('/v1/ai/prompts/reset'); await loadAI() } catch (error) { showError(error instanceof Error ? error.message : 'Prompt reset failed') } })
  $('aiPromptForm').addEventListener('submit', async (event) => { event.preventDefault(); try { await savePrompt(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'Prompt save failed') } })
  $('aiTaskForm').addEventListener('submit', async (event) => { event.preventDefault(); try { await submitAITask(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'AI task submission failed') } })
  $('aiHistoryClearButton').addEventListener('click', async () => { if (!window.confirm('Clear all AI history?')) return; try { await postJson('/v1/ai/history/clear'); $('aiHistoryDetail').classList.add('is-hidden'); await loadAI() } catch (error) { showError(error instanceof Error ? error.message : 'History clear failed') } })

  $('subsRefreshButton').addEventListener('click', loadSubscriptions)
  $('subsNewButton').addEventListener('click', () => { state.selectedSubscriptionId = ''; renderSubscriptions(); openSubscriptionEditor(null) })
  $('subsCancelButton').addEventListener('click', closeSubscriptionEditor)
  $('subsForm').addEventListener('submit', async (event) => { event.preventDefault(); try { await saveSubscription(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'Subscription save failed') } })
  $('subsDeleteButton').addEventListener('click', async () => { if (!state.selectedSubscriptionId || !window.confirm('Delete this subscription and its v2 state?')) return; try { await postJson(`/v1/subscriptions/${encodeURIComponent(state.selectedSubscriptionId)}/delete`); closeSubscriptionEditor(); await loadSubscriptions() } catch (error) { showError(error instanceof Error ? error.message : 'Subscription delete failed') } })
  $('subsRulesForm').addEventListener('submit', async (event) => { event.preventDefault(); try { await saveSubscriptionRules(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'Rule save failed') } })
  $('subsReconcileButton').addEventListener('click', async () => { try { await reconcileSubscription(); showError('') } catch (error) { showError(error instanceof Error ? error.message : 'Reconcile failed') } })
  $('subsItemState').addEventListener('change', async () => { try { await loadSubscriptionItems() } catch (error) { showError(error instanceof Error ? error.message : 'Unable to filter subscription items') } })
})()
