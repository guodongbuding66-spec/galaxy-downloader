(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))
  const state = { status: null, entries: [], query: '', selectedId: '' }

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

  function post(path) { return api(path, { method: 'POST' }) }

  function showError(message) {
    if (!$('errorNotice')) return
    $('errorText').textContent = message || ''
    $('errorNotice').classList.toggle('is-hidden', !message)
  }

  function injectShell() {
    const nav = document.querySelector('.sidebar nav')
    const main = document.querySelector('.main')
    if (!nav || !main || $('pluginsView')) return

    const button = document.createElement('button')
    button.className = 'nav-item'
    button.type = 'button'
    button.dataset.pluginView = 'plugins'
    button.textContent = 'Plugins'
    nav.appendChild(button)

    const section = document.createElement('section')
    section.id = 'pluginsView'
    section.className = 'view is-hidden plugin-view'
    section.innerHTML = `
      <div class="metrics" aria-label="Plugin summary">
        <article class="metric"><span>Installed</span><strong id="pluginInstalledCount">0</strong><small>local plugins</small></article>
        <article class="metric"><span>Enabled</span><strong id="pluginEnabledCount">0</strong><small>active plugins</small></article>
        <article class="metric"><span>Updates</span><strong id="pluginUpdateCount">0</strong><small>available</small></article>
        <article class="metric"><span>Marketplace</span><strong id="pluginMarketCount">0</strong><small>cached entries</small></article>
        <article class="metric"><span>Capabilities</span><strong id="pluginCapabilityCount">0</strong><small>allowed by host</small></article>
      </div>
      <section class="panel">
        <div class="panel-header plugin-header">
          <div><h2>Plugins</h2><p id="pluginSourceMeta">Marketplace cache and installed plugin management.</p></div>
          <div class="toolbar"><button class="button secondary" id="pluginRefreshButton" type="button">Refresh</button><button class="button secondary" id="pluginMarketplaceRefreshButton" type="button">Refresh Marketplace</button><button class="button primary" id="pluginUpdateAllButton" type="button" disabled>Update All</button></div>
        </div>
        <form class="filterbar" id="pluginFilterForm"><label class="field grow" for="pluginSearch"><span>Search</span><input id="pluginSearch" type="search" autocomplete="off" placeholder="Plugin name, ID, description or capability"></label><label class="field" for="pluginMode"><span>Show</span><select id="pluginMode"><option value="all">All</option><option value="installed">Installed</option><option value="updates">Updates</option><option value="available">Not installed</option></select></label><button class="button primary filter-submit" type="submit">Apply</button><button class="button secondary filter-submit" id="pluginResetButton" type="button">Reset</button></form>
        <div id="pluginList" class="plugin-list"><div class="empty">Open Plugins to load the marketplace.</div></div>
      </section>
      <section id="pluginDetailPanel" class="panel section-gap is-hidden"><div class="panel-header"><div><h2 id="pluginDetailTitle">Plugin</h2><p id="pluginDetailMeta"></p></div><button class="button secondary" id="pluginDetailClose" type="button">Close</button></div><div id="pluginDetailBody" class="plugin-detail-body"></div></section>`
    main.appendChild(section)
  }

  function hideOtherViews() {
    document.querySelectorAll('.main > .view').forEach((view) => view.classList.add('is-hidden'))
    document.querySelectorAll('.sidebar .nav-item').forEach((button) => button.classList.remove('is-active'))
  }

  function showPlugins() {
    hideOtherViews()
    $('pluginsView').classList.remove('is-hidden')
    document.querySelector('[data-plugin-view="plugins"]')?.classList.add('is-active')
    $('viewTitle').textContent = 'Plugins'
    loadPlugins()
  }

  function hidePlugins() {
    $('pluginsView')?.classList.add('is-hidden')
    document.querySelector('[data-plugin-view="plugins"]')?.classList.remove('is-active')
  }

  function installedMap() {
    const rows = Array.isArray(state.status?.plugins) ? state.status.plugins : []
    return new Map(rows.map((plugin) => [plugin.id, plugin]))
  }

  function mergedRows() {
    const installed = installedMap()
    const byId = new Map()
    for (const entry of state.entries) byId.set(entry.id, { ...entry, installedPlugin: installed.get(entry.id) || null })
    for (const plugin of installed.values()) {
      if (!byId.has(plugin.id)) {
        byId.set(plugin.id, { id: plugin.id, name: plugin.name, version: plugin.version, capabilities: plugin.capabilities || [], description: '', platforms: [], installed: true, installedVersion: plugin.version, enabled: plugin.enabled, updateAvailable: false, installedPlugin: plugin })
      }
    }
    return [...byId.values()].sort((a, b) => String(a.name || a.id).localeCompare(String(b.name || b.id)))
  }

  function filteredRows() {
    const query = state.query.toLowerCase()
    const mode = $('pluginMode')?.value || 'all'
    return mergedRows().filter((row) => {
      if (mode === 'installed' && !row.installed) return false
      if (mode === 'updates' && !row.updateAvailable) return false
      if (mode === 'available' && row.installed) return false
      if (!query) return true
      const haystack = [row.id, row.name, row.description, ...(row.capabilities || []), ...(row.platforms || [])].join(' ').toLowerCase()
      return haystack.includes(query)
    })
  }

  function capabilityChips(values) {
    return (Array.isArray(values) ? values : []).slice(0, 12).map((value) => `<span class="plugin-chip">${esc(value)}</span>`).join('')
  }

  function rowActions(row) {
    const actions = []
    if (row.installed) {
      actions.push(`<button class="action" data-plugin-detail="${esc(row.id)}" type="button">Detail</button>`)
      actions.push(`<button class="action" data-plugin-toggle="${esc(row.id)}" data-plugin-enabled="${row.enabled ? 'false' : 'true'}" type="button">${row.enabled ? 'Disable' : 'Enable'}</button>`)
      if (row.updateAvailable) actions.push(`<button class="action" data-plugin-update="${esc(row.id)}" type="button">Update</button>`)
      actions.push(`<button class="action danger-text" data-plugin-remove="${esc(row.id)}" type="button">Remove</button>`)
    } else {
      actions.push(`<button class="action" data-plugin-install="${esc(row.id)}" type="button">Install</button>`)
    }
    return actions.join('')
  }

  function render() {
    const installed = Array.isArray(state.status?.plugins) ? state.status.plugins : []
    const updates = state.entries.filter((entry) => entry.updateAvailable)
    $('pluginInstalledCount').textContent = String(installed.length)
    $('pluginEnabledCount').textContent = String(installed.filter((plugin) => plugin.enabled).length)
    $('pluginUpdateCount').textContent = String(updates.length)
    $('pluginMarketCount').textContent = String(state.entries.length)
    $('pluginCapabilityCount').textContent = String(Array.isArray(state.status?.capabilities) ? state.status.capabilities.length : 0)
    $('pluginUpdateAllButton').disabled = updates.length === 0
    $('pluginSourceMeta').textContent = state.status?.marketplaceCached ? `${state.entries.length} cached marketplace entries · ${updates.length} update${updates.length === 1 ? '' : 's'} available` : 'Marketplace cache is empty. Refresh Marketplace to load signed entries.'

    const rows = filteredRows()
    $('pluginList').innerHTML = rows.length ? rows.map((row) => `<article class="plugin-row"><div class="plugin-main"><div class="plugin-title-line"><strong>${esc(row.name || row.id)}</strong><span class="plugin-state ${row.installed ? 'installed' : ''}">${row.installed ? (row.enabled ? 'Enabled' : 'Disabled') : 'Available'}</span>${row.updateAvailable ? '<span class="plugin-state update">Update</span>' : ''}</div><span>${esc(row.id)} · ${esc(row.installedVersion || row.version || '—')}${row.installed && row.version && row.installedVersion !== row.version ? ` → ${esc(row.version)}` : ''}</span><p>${esc(row.description || 'No marketplace description.')}</p><div class="plugin-chips">${capabilityChips(row.capabilities)}</div></div><div class="plugin-platforms">${(row.platforms || []).length ? esc((row.platforms || []).join(' · ')) : 'Local install'}</div><div class="plugin-actions">${rowActions(row)}</div></article>`).join('') : '<div class="empty">No plugins match this filter.</div>'
  }

  async function loadPlugins() {
    $('pluginList').innerHTML = '<div class="empty">Loading plugins…</div>'
    try {
      const [status, marketplace] = await Promise.all([api('/v1/plugins/status'), api('/v1/plugins/marketplace')])
      state.status = status
      state.entries = Array.isArray(marketplace.entries) ? marketplace.entries : []
      render()
      showError('')
    } catch (error) {
      $('pluginList').innerHTML = '<div class="empty">Plugin service is unavailable.</div>'
      showError(error instanceof Error ? error.message : 'Unable to load plugins')
    }
  }

  async function refreshMarketplace() {
    $('pluginMarketplaceRefreshButton').disabled = true
    try {
      await post('/v1/plugins/marketplace/refresh')
      await loadPlugins()
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Marketplace refresh failed')
    } finally {
      $('pluginMarketplaceRefreshButton').disabled = false
    }
  }

  async function pluginAction(id, action) {
    await post(`/v1/plugins/${encodeURIComponent(id)}/${action}`)
    await loadPlugins()
  }

  async function updateAll() {
    const updates = state.entries.filter((entry) => entry.updateAvailable)
    if (!updates.length) return
    $('pluginUpdateAllButton').disabled = true
    try {
      for (const entry of updates) await post(`/v1/plugins/${encodeURIComponent(entry.id)}/update`)
      await loadPlugins()
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Plugin update failed')
      await loadPlugins()
    }
  }

  async function showDetail(id) {
    const result = await api(`/v1/plugins/${encodeURIComponent(id)}`)
    const plugin = result.plugin || {}
    const market = result.marketplace || null
    state.selectedId = id
    $('pluginDetailPanel').classList.remove('is-hidden')
    $('pluginDetailTitle').textContent = plugin.name || market?.name || id
    $('pluginDetailMeta').textContent = `${id} · installed ${plugin.version || '—'}${market?.version ? ` · marketplace ${market.version}` : ''}`
    $('pluginDetailBody').innerHTML = `<dl><div><dt>Status</dt><dd>${plugin.enabled ? 'Enabled' : 'Disabled'}</dd></div><div><dt>Capabilities</dt><dd>${esc((plugin.capabilities || []).join(', ') || '—')}</dd></div><div><dt>Update</dt><dd>${market?.updateAvailable ? 'Available' : 'Current / unavailable'}</dd></div><div><dt>Package host</dt><dd>${esc(market?.packageHost || '—')}</dd></div><div><dt>Platforms</dt><dd>${esc((market?.platforms || []).join(', ') || '—')}</dd></div></dl><p>${esc(market?.description || 'No marketplace description available for this installed plugin.')}</p>`
    $('pluginDetailPanel').scrollIntoView({ block: 'nearest' })
  }

  injectShell()

  document.addEventListener('click', async (event) => {
    const pluginView = event.target.closest('[data-plugin-view]')
    if (pluginView) { showPlugins(); return }
    if (event.target.closest('[data-view], [data-view-jump], [data-ops-view]')) hidePlugins()

    try {
      const detail = event.target.closest('[data-plugin-detail]')
      if (detail) await showDetail(detail.dataset.pluginDetail)
      const toggle = event.target.closest('[data-plugin-toggle]')
      if (toggle) await pluginAction(toggle.dataset.pluginToggle, toggle.dataset.pluginEnabled === 'true' ? 'enable' : 'disable')
      const install = event.target.closest('[data-plugin-install]')
      if (install) await pluginAction(install.dataset.pluginInstall, 'install')
      const update = event.target.closest('[data-plugin-update]')
      if (update) await pluginAction(update.dataset.pluginUpdate, 'update')
      const remove = event.target.closest('[data-plugin-remove]')
      if (remove && window.confirm('Remove this installed plugin?')) await pluginAction(remove.dataset.pluginRemove, 'remove')
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Plugin operation failed')
    }
  })

  $('pluginRefreshButton').addEventListener('click', loadPlugins)
  $('pluginMarketplaceRefreshButton').addEventListener('click', refreshMarketplace)
  $('pluginUpdateAllButton').addEventListener('click', updateAll)
  $('pluginDetailClose').addEventListener('click', () => $('pluginDetailPanel').classList.add('is-hidden'))
  $('pluginFilterForm').addEventListener('submit', (event) => { event.preventDefault(); state.query = $('pluginSearch').value.trim(); render() })
  $('pluginResetButton').addEventListener('click', () => { state.query = ''; $('pluginSearch').value = ''; $('pluginMode').value = 'all'; render() })
  $('pluginMode').addEventListener('change', render)
  $('refreshButton')?.addEventListener('click', () => { if (!$('pluginsView').classList.contains('is-hidden')) loadPlugins() })
})()
