(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const state = { settings: null }

  function authHeaders(extra = {}) {
    const headers = { Accept: 'application/json', ...extra }
    const token = sessionStorage.getItem('galaxy.headless.token') || ''
    if (token) headers.Authorization = `Bearer ${token}`
    return headers
  }

  async function api(path) {
    const response = await fetch(path, { headers: authHeaders(), cache: 'no-store' })
    if (response.status === 401) {
      $('credentialsPanel')?.classList.remove('is-hidden')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function showError(message) {
    const notice = $('errorNotice')
    if (!notice) return
    $('errorText').textContent = message || ''
    notice.classList.toggle('is-hidden', !message)
  }

  function injectStyles() {
    if (document.querySelector('link[data-settings-style]')) return
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = '/dashboard/settings.css'
    link.dataset.settingsStyle = 'true'
    document.head.appendChild(link)
  }

  function injectShell() {
    const nav = document.querySelector('.sidebar nav')
    const main = document.querySelector('.main')
    if (!nav || !main || $('settingsView')) return

    const button = document.createElement('button')
    button.className = 'nav-item'
    button.type = 'button'
    button.dataset.settingsView = 'settings'
    button.textContent = 'Settings'
    nav.appendChild(button)

    const section = document.createElement('section')
    section.id = 'settingsView'
    section.className = 'view is-hidden settings-view'
    section.innerHTML = `
      <div class="metrics" aria-label="Runtime settings summary">
        <article class="metric"><span>Binding</span><strong id="settingsBinding">—</strong><small>runtime mode</small></article>
        <article class="metric"><span>Remote</span><strong id="settingsRemote">—</strong><small>network access</small></article>
        <article class="metric"><span>Auth</span><strong id="settingsAuth">—</strong><small id="settingsAuthDetail">checking</small></article>
        <article class="metric"><span>Queue</span><strong id="settingsQueue">—</strong><small>capacity</small></article>
        <article class="metric"><span>Features</span><strong id="settingsFeatureCount">—</strong><small>available modules</small></article>
      </div>

      <div class="settings-grid">
        <section class="panel settings-runtime-panel">
          <div class="panel-header"><div><h2>Runtime & Security</h2><p>Safe runtime state from the read-only Headless Settings contract.</p></div><div class="toolbar"><button class="button secondary" id="settingsRefreshButton" type="button">Refresh</button><button class="button secondary" id="settingsCredentialsButton" type="button">Credentials</button></div></div>
          <dl class="settings-facts" id="settingsFacts">
            <div><dt>Binding mode</dt><dd id="settingsFactBinding">—</dd></div>
            <div><dt>Remote access</dt><dd id="settingsFactRemote">—</dd></div>
            <div><dt>Authentication</dt><dd id="settingsFactAuth">—</dd></div>
            <div><dt>Bearer configured</dt><dd id="settingsFactConfigured">—</dd></div>
            <div><dt>Bearer required</dt><dd id="settingsFactRequired">—</dd></div>
            <div><dt>Queue capacity</dt><dd id="settingsFactQueue">—</dd></div>
          </dl>
          <div class="settings-security-note" id="settingsSecurityNote" role="status">Loading runtime security state…</div>
        </section>

        <section class="panel settings-features-panel">
          <div class="panel-header"><div><h2>Features</h2><p id="settingsFeaturesMeta">Loading module availability…</p></div></div>
          <div id="settingsFeatureList" class="settings-feature-list"><div class="empty">Loading…</div></div>
        </section>
      </div>

      <section class="panel section-gap settings-config-panel">
        <div class="panel-header"><div><h2>Configuration</h2><p id="settingsConfigMeta">Runtime configuration is intentionally read-only in the Web Dashboard.</p></div></div>
        <div class="settings-readonly-banner"><strong>Read-only</strong><span>Change these settings through environment variables or CLI, then restart the Headless service. Current values are intentionally not returned to the browser.</span></div>
        <div class="settings-config-head"><span>Variable</span><span>Classification</span><span>Apply</span></div>
        <div id="settingsEnvironmentList" class="settings-env-list"><div class="empty">Loading configuration metadata…</div></div>
      </section>`
    main.appendChild(section)
  }

  function hideOtherViews() {
    document.querySelectorAll('.main > .view').forEach((view) => view.classList.add('is-hidden'))
    document.querySelectorAll('.sidebar .nav-item').forEach((button) => button.classList.remove('is-active'))
  }

  function hideSettings() {
    $('settingsView')?.classList.add('is-hidden')
    document.querySelector('[data-settings-view="settings"]')?.classList.remove('is-active')
  }

  function showSettings() {
    hideOtherViews()
    $('settingsView').classList.remove('is-hidden')
    document.querySelector('[data-settings-view="settings"]')?.classList.add('is-active')
    $('viewTitle').textContent = 'Settings'
    loadSettings()
  }

  function setText(id, value) {
    const element = $(id)
    if (element) element.textContent = String(value ?? '—')
  }

  function humanFeature(name) {
    const labels = {
      ai: 'AI',
      asr: 'ASR',
      downloads: 'Downloads',
      learning: 'Learning',
      media: 'Media Library',
      music: 'Music',
      plugins: 'Plugins',
      reader: 'Reader',
      subscriptions: 'Subscriptions',
      transcript: 'Transcript',
      transfer: 'Transfer',
      webDashboard: 'Web Dashboard',
      whisperx: 'WhisperX',
    }
    return labels[name] || name
  }

  function statusPill(text, tone = '') {
    const span = document.createElement('span')
    span.className = `settings-pill${tone ? ` ${tone}` : ''}`
    span.textContent = text
    return span
  }

  function renderFeatures(features) {
    const list = $('settingsFeatureList')
    list.replaceChildren()
    const rows = Object.entries(features || {}).sort(([a], [b]) => humanFeature(a).localeCompare(humanFeature(b)))
    const enabled = rows.filter(([, value]) => Boolean(value)).length
    setText('settingsFeatureCount', `${enabled}/${rows.length}`)
    setText('settingsFeaturesMeta', `${enabled} of ${rows.length} production modules available`)

    if (!rows.length) {
      const empty = document.createElement('div')
      empty.className = 'empty'
      empty.textContent = 'No feature capability metadata was returned.'
      list.appendChild(empty)
      return
    }

    for (const [key, value] of rows) {
      const row = document.createElement('div')
      row.className = 'settings-feature-row'
      const name = document.createElement('div')
      const strong = document.createElement('strong')
      strong.textContent = humanFeature(key)
      const code = document.createElement('span')
      code.textContent = key
      name.append(strong, code)
      row.append(name, statusPill(value ? 'Available' : 'Unavailable', value ? 'ok' : 'muted'))
      list.appendChild(row)
    }
  }

  function renderEnvironment(configuration) {
    const list = $('settingsEnvironmentList')
    list.replaceChildren()
    const rows = Array.isArray(configuration?.environment) ? configuration.environment : []
    const mode = configuration?.mode || 'environment-or-cli'
    setText('settingsConfigMeta', `Mode: ${mode} · Web writes: ${configuration?.writable ? 'reported writable' : 'disabled'}`)

    if (!rows.length) {
      const empty = document.createElement('div')
      empty.className = 'empty'
      empty.textContent = 'No configuration metadata was returned.'
      list.appendChild(empty)
      return
    }

    for (const item of rows) {
      const row = document.createElement('div')
      row.className = 'settings-env-row'
      const variable = document.createElement('code')
      variable.textContent = item.name || 'UNKNOWN'

      const classification = document.createElement('div')
      classification.className = 'settings-pill-group'
      if (item.secret) classification.appendChild(statusPill('Secret', 'danger'))
      else if (item.sensitive) classification.appendChild(statusPill('Sensitive', 'warn'))
      else classification.appendChild(statusPill('Non-secret', 'muted'))

      const apply = document.createElement('span')
      apply.className = 'settings-apply'
      apply.textContent = item.restartRequired ? 'Restart required' : 'Runtime'
      row.append(variable, classification, apply)
      list.appendChild(row)
    }
  }

  function render(settings) {
    const authentication = settings.authentication || {}
    const binding = settings.bindingMode || 'unknown'
    const remote = Boolean(settings.remoteAccess)
    const authMode = authentication.mode || 'none'
    const configured = Boolean(authentication.configured)
    const required = Boolean(authentication.required)
    const queueCapacity = Number(settings.queue?.capacity) || 0

    setText('settingsBinding', binding)
    setText('settingsRemote', remote ? 'Enabled' : 'Off')
    setText('settingsAuth', authMode === 'bearer' ? 'Bearer' : 'None')
    setText('settingsAuthDetail', required ? 'required' : configured ? 'configured' : 'not configured')
    setText('settingsQueue', queueCapacity || '—')

    setText('settingsFactBinding', binding)
    setText('settingsFactRemote', remote ? 'Enabled' : 'Loopback only')
    setText('settingsFactAuth', authMode)
    setText('settingsFactConfigured', configured ? 'Yes' : 'No')
    setText('settingsFactRequired', required ? 'Yes' : 'No')
    setText('settingsFactQueue', queueCapacity || '—')

    const note = $('settingsSecurityNote')
    note.classList.toggle('is-warning', remote && !configured)
    if (remote && required && configured) note.textContent = 'Remote binding is active and Bearer authentication is required. Credential values remain outside this Settings response.'
    else if (remote && required) note.textContent = 'Remote binding requires Bearer authentication. Configure the token outside the Web Dashboard before exposing the service.'
    else if (configured) note.textContent = 'Loopback binding is active. A Bearer token is configured, but remote authentication is not required while the service remains loopback-only.'
    else note.textContent = 'Loopback-only mode is active. Remote access is disabled and no Bearer token is configured.'

    renderFeatures(settings.features || {})
    renderEnvironment(settings.configuration || {})
  }

  async function loadSettings() {
    setText('settingsSecurityNote', 'Loading runtime security state…')
    try {
      const result = await api('/v1/settings')
      state.settings = result.settings || {}
      render(state.settings)
      showError('')
    } catch (error) {
      state.settings = null
      setText('settingsSecurityNote', 'Runtime Settings could not be loaded.')
      showError(error instanceof Error ? error.message : 'Unable to load runtime settings')
    }
  }

  injectStyles()
  injectShell()

  document.addEventListener('click', (event) => {
    const settingsView = event.target.closest('[data-settings-view]')
    if (settingsView) {
      showSettings()
      return
    }
    if (event.target.closest('[data-view], [data-view-jump], [data-ops-view], [data-plugin-view]')) hideSettings()
  })

  $('settingsRefreshButton').addEventListener('click', loadSettings)
  $('settingsCredentialsButton').addEventListener('click', () => {
    $('credentialsButton')?.click()
    $('tokenInput')?.focus()
  })
  $('refreshButton')?.addEventListener('click', () => {
    if (!$('settingsView').classList.contains('is-hidden')) loadSettings()
  })
})()
