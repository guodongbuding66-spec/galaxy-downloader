(() => {
  'use strict'

  const $ = (id) => document.getElementById(id)
  const idPattern = /^[a-f0-9]{16,64}$/
  const playbackPathPattern = /^\/v1\/music\/playback\/[A-Za-z0-9_-]{32,128}\/[a-f0-9]{16,64}$/
  const PROGRESS_INTERVAL_SECONDS = 10
  const state = {
    songs: [],
    queue: [],
    player: { currentMediaId: '', repeatMode: 'off', shuffle: false, volume: 1 },
    query: '',
    favoritesOnly: false,
    currentSong: null,
    audio: null,
    loading: false,
    lastSavedSeconds: 0,
    lastQueuedSeconds: 0,
    saveChain: Promise.resolve(),
    volumeTimer: 0,
  }

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[char]))

  function mediaId(value) {
    const clean = String(value || '').trim().toLowerCase()
    return idPattern.test(clean) ? clean : ''
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
    if (response.status === 401) {
      $('credentialsPanel')?.classList.remove('is-hidden')
      throw new Error('Headless API requires a valid Bearer token')
    }
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`)
    return payload
  }

  function postJson(path, payload = {}) {
    return api(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
  }

  function setStatus(message, tone = '') {
    const node = $('musicStatus')
    if (!node) return
    node.textContent = String(message || '')
    node.dataset.tone = tone
  }

  function showError(message) {
    const notice = $('errorNotice')
    if (!notice) return
    $('errorText').textContent = message || ''
    notice.classList.toggle('is-hidden', !message)
  }

  function formatDuration(value) {
    const total = Math.max(0, Math.floor(Number(value) || 0))
    if (!total) return '—'
    const hours = Math.floor(total / 3600)
    const minutes = Math.floor((total % 3600) / 60)
    const seconds = total % 60
    return hours
      ? `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
      : `${minutes}:${String(seconds).padStart(2, '0')}`
  }

  function installSurface() {
    if (!$('musicNavButton')) {
      const nav = document.querySelector('.sidebar nav')
      const button = document.createElement('button')
      button.id = 'musicNavButton'
      button.className = 'nav-item'
      button.type = 'button'
      button.dataset.musicView = 'music'
      button.textContent = 'Music'
      const library = document.querySelector('[data-view="library"]')
      if (nav && library?.parentNode === nav) library.insertAdjacentElement('afterend', button)
      else nav?.appendChild(button)
    }

    if ($('musicView')) return
    const main = document.querySelector('.main')
    if (!main) return
    const view = document.createElement('section')
    view.id = 'musicView'
    view.className = 'view is-hidden music-view'
    view.innerHTML = `
      <div class="music-metrics" aria-label="音乐库摘要">
        <article class="metric"><span>Songs</span><strong id="musicSongCount">0</strong><small>filtered tracks</small></article>
        <article class="metric"><span>Favorites</span><strong id="musicFavoriteCount">0</strong><small>in current result</small></article>
        <article class="metric"><span>Queue</span><strong id="musicQueueCount">0</strong><small>playback order</small></article>
        <article class="metric"><span>Player</span><strong id="musicPlayerState">Idle</strong><small id="musicPlayerStateDetail">nothing selected</small></article>
      </div>

      <div class="music-layout">
        <section class="panel music-library-panel">
          <div class="panel-header music-panel-header">
            <div><h2>Music Library</h2><p>Play indexed local audio without exposing filesystem paths.</p></div>
            <div class="toolbar">
              <button class="button secondary" id="musicSyncButton" type="button">Sync Library</button>
              <button class="button secondary" id="musicRefreshButton" type="button">Refresh</button>
            </div>
          </div>
          <form class="music-filterbar" id="musicSearchForm">
            <label class="field grow" for="musicSearch"><span>Search</span><input id="musicSearch" type="search" autocomplete="off" placeholder="Title, artist, album or genre"></label>
            <label class="music-check"><input id="musicFavoritesOnly" type="checkbox"><span>Favorites only</span></label>
            <button class="button primary" type="submit">Apply</button>
            <button class="button secondary" id="musicClearSearch" type="button">Clear</button>
          </form>
          <div id="musicSongs" class="music-song-list"><div class="empty">Open Music to load your library.</div></div>
        </section>

        <div class="music-side-stack">
          <section class="panel music-player-panel" aria-labelledby="musicNowPlayingTitle">
            <div class="panel-header"><div><h2 id="musicNowPlayingTitle">Now Playing</h2><p id="musicNowPlayingMeta">Select a track to begin.</p></div></div>
            <div class="music-player-body">
              <div class="music-now-playing">
                <strong id="musicCurrentTitle">No track selected</strong>
                <span id="musicCurrentArtist">—</span>
              </div>
              <audio id="musicAudio" class="music-audio" controls preload="metadata"></audio>
              <div class="music-transport" aria-label="Playback controls">
                <button class="button secondary" id="musicPrevious" type="button" disabled>Previous</button>
                <button class="button secondary" id="musicNext" type="button" disabled>Next</button>
              </div>
              <div class="music-player-options">
                <label class="field" for="musicRepeat"><span>Repeat</span><select id="musicRepeat"><option value="off">Off</option><option value="all">All</option><option value="one">One</option></select></label>
                <label class="music-check music-option-check"><input id="musicShuffle" type="checkbox"><span>Shuffle</span></label>
                <label class="field music-volume-field" for="musicVolume"><span>Volume</span><input id="musicVolume" type="range" min="0" max="1" step="0.05" value="1"></label>
              </div>
              <div id="musicStatus" class="music-status" aria-live="polite">Ready.</div>
            </div>
          </section>

          <section class="panel music-queue-panel">
            <div class="panel-header"><div><h2>Queue</h2><p id="musicQueueMeta">0 tracks</p></div><button class="button secondary" id="musicClearQueue" type="button" disabled>Clear</button></div>
            <div id="musicQueue" class="music-queue-list"><div class="empty small-empty">Queue is empty.</div></div>
          </section>

          <section class="panel music-lyrics-panel">
            <div class="panel-header"><div><h2>Lyrics</h2><p id="musicLyricsMeta">Select a track.</p></div></div>
            <pre id="musicLyrics" class="music-lyrics" tabindex="0">No lyrics loaded.</pre>
          </section>
        </div>
      </div>`

    const anchor = $('aiView') || $('subscriptionsView')
    if (anchor?.parentNode === main) main.insertBefore(view, anchor)
    else main.appendChild(view)

    state.audio = $('musicAudio')
    bindSurfaceEvents()
  }

  function hideCoreAndOpsViews() {
    for (const id of ['dashboardView', 'downloadsView', 'libraryView', 'transcriptView', 'aiView', 'subscriptionsView']) {
      $(id)?.classList.add('is-hidden')
    }
    document.querySelectorAll('[data-view], [data-ops-view]').forEach((button) => button.classList.remove('is-active'))
  }

  function closeMusicView() {
    $('musicView')?.classList.add('is-hidden')
    $('musicNavButton')?.classList.remove('is-active')
  }

  async function showMusicView() {
    installSurface()
    hideCoreAndOpsViews()
    $('musicView')?.classList.remove('is-hidden')
    $('musicNavButton')?.classList.add('is-active')
    if ($('viewTitle')) $('viewTitle').textContent = 'Music'
    await loadMusic({ prepareCurrent: true })
  }

  function currentSongFromCollections() {
    const id = mediaId(state.player.currentMediaId)
    if (!id) return null
    return state.songs.find((song) => mediaId(song.mediaId) === id)
      || state.queue.map((row) => row?.track).find((song) => mediaId(song?.mediaId) === id)
      || null
  }

  function renderSongs() {
    const container = $('musicSongs')
    if (!container) return
    $('musicSongCount').textContent = String(state.songs.length)
    $('musicFavoriteCount').textContent = String(state.songs.filter((song) => Boolean(song.favorite)).length)
    if (!state.songs.length) {
      container.innerHTML = '<div class="empty">No music tracks match this filter.</div>'
      return
    }
    container.innerHTML = state.songs.map((song) => {
      const id = mediaId(song.mediaId)
      if (!id) return ''
      const active = id === mediaId(state.player.currentMediaId)
      return `<article class="music-song-row${active ? ' is-current' : ''}" data-music-song-row="${esc(id)}">
        <button class="music-song-main" data-music-play="${esc(id)}" type="button" aria-label="Play ${esc(song.title || 'track')}">
          <strong>${esc(song.title || 'Unknown Track')}</strong>
          <span>${esc(song.artist || 'Unknown Artist')}${song.album ? ` · ${esc(song.album)}` : ''}${song.year ? ` · ${esc(song.year)}` : ''}</span>
        </button>
        <span class="music-duration numeric">${esc(formatDuration(song.durationSeconds))}</span>
        <button class="action music-favorite" data-music-favorite="${esc(id)}" type="button" aria-pressed="${song.favorite ? 'true' : 'false'}" aria-label="${song.favorite ? 'Remove from favorites' : 'Add to favorites'}">${song.favorite ? '★' : '☆'}</button>
        <button class="action" data-music-enqueue="${esc(id)}" type="button">Queue</button>
      </article>`
    }).join('')
  }

  function renderQueue() {
    const container = $('musicQueue')
    if (!container) return
    $('musicQueueCount').textContent = String(state.queue.length)
    $('musicQueueMeta').textContent = `${state.queue.length} track${state.queue.length === 1 ? '' : 's'}`
    $('musicClearQueue').disabled = state.queue.length === 0
    $('musicPrevious').disabled = state.queue.length === 0 || state.loading
    $('musicNext').disabled = state.queue.length === 0 || state.loading
    if (!state.queue.length) {
      container.innerHTML = '<div class="empty small-empty">Queue is empty.</div>'
      return
    }
    container.innerHTML = state.queue.map((row) => {
      const id = mediaId(row?.track?.mediaId)
      if (!id) return ''
      const current = id === mediaId(state.player.currentMediaId)
      return `<article class="music-queue-row${current ? ' is-current' : ''}">
        <button class="music-queue-main" data-music-queue-play="${esc(id)}" type="button"><span class="numeric">${esc(row.position || '')}</span><span><strong>${esc(row.track.title || 'Unknown Track')}</strong><small>${esc(row.track.artist || 'Unknown Artist')}</small></span></button>
        <button class="action" data-music-queue-remove="${esc(row.id || '')}" type="button" aria-label="Remove ${esc(row.track.title || 'track')} from queue">Remove</button>
      </article>`
    }).join('')
  }

  function renderPlayer() {
    const song = state.currentSong || currentSongFromCollections()
    const player = state.player || {}
    $('musicRepeat').value = ['off', 'all', 'one'].includes(String(player.repeatMode || '')) ? player.repeatMode : 'off'
    $('musicShuffle').checked = Boolean(player.shuffle)
    const volume = Math.max(0, Math.min(Number(player.volume ?? 1), 1))
    $('musicVolume').value = String(volume)
    if (state.audio && Math.abs(state.audio.volume - volume) > 0.01) state.audio.volume = volume
    if (song) {
      $('musicCurrentTitle').textContent = song.title || 'Unknown Track'
      $('musicCurrentArtist').textContent = song.artist || 'Unknown Artist'
      $('musicNowPlayingMeta').textContent = `${song.album || 'Unknown Album'} · ${formatDuration(song.durationSeconds)}`
      $('musicPlayerState').textContent = state.audio && !state.audio.paused ? 'Playing' : 'Ready'
      $('musicPlayerStateDetail').textContent = song.title || 'selected track'
    } else {
      $('musicCurrentTitle').textContent = 'No track selected'
      $('musicCurrentArtist').textContent = '—'
      $('musicNowPlayingMeta').textContent = 'Select a track to begin.'
      $('musicPlayerState').textContent = 'Idle'
      $('musicPlayerStateDetail').textContent = 'nothing selected'
    }
    renderSongs()
    renderQueue()
  }

  function renderLyrics(payload, song) {
    const node = $('musicLyrics')
    if (!node) return
    const lyrics = payload?.lyrics && typeof payload.lyrics === 'object' ? payload.lyrics : null
    $('musicLyricsMeta').textContent = song ? `${song.artist || 'Unknown Artist'} — ${song.title || 'Unknown Track'}` : 'Select a track.'
    if (!lyrics) {
      node.textContent = 'No lyrics available.'
      return
    }
    const synced = Array.isArray(lyrics.synced) ? lyrics.synced.slice(0, 5000) : []
    if (synced.length) {
      node.textContent = synced.map((row) => `${formatDuration(row.time)}  ${String(row.text || '').trim()}`).filter((line) => line.trim()).join('\n') || 'No lyrics available.'
      return
    }
    node.textContent = String(lyrics.text || '').trim() || 'No lyrics available.'
  }

  async function loadLyrics(song) {
    const id = mediaId(song?.mediaId)
    if (!id) {
      renderLyrics(null, null)
      return
    }
    try {
      const payload = await api(`/v1/music/songs/${encodeURIComponent(id)}/lyrics`)
      if (mediaId(state.currentSong?.mediaId) === id) renderLyrics(payload, song)
    } catch {
      if (mediaId(state.currentSong?.mediaId) === id) renderLyrics(null, song)
    }
  }

  async function loadMusic({ prepareCurrent = false } = {}) {
    installSurface()
    setStatus('Loading music library…')
    $('musicRefreshButton').disabled = true
    try {
      const params = new URLSearchParams({ limit: '2000' })
      if (state.query) params.set('q', state.query)
      if (state.favoritesOnly) params.set('favoritesOnly', 'true')
      const [songs, queue, player] = await Promise.all([
        api(`/v1/music/songs?${params.toString()}`),
        api('/v1/music/queue'),
        api('/v1/music/player'),
      ])
      state.songs = Array.isArray(songs.songs) ? songs.songs : []
      state.queue = Array.isArray(queue.queue) ? queue.queue : []
      state.player = player?.player && typeof player.player === 'object' ? player.player : state.player
      state.currentSong = currentSongFromCollections()
      renderPlayer()
      showError('')
      setStatus(`${state.songs.length} tracks loaded.`, 'success')
      if (prepareCurrent && state.currentSong && (!state.audio?.src || mediaId(state.currentSong.mediaId) !== mediaId(state.audio?.dataset.mediaId))) {
        await prepareSong(state.currentSong, { autoplay: false, incrementPlay: false, resume: true, updatePlayer: false })
      }
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Unable to load Music')
      setStatus('Music library could not be loaded.', 'error')
    } finally {
      $('musicRefreshButton').disabled = false
    }
  }

  async function issuePlayback(id) {
    const payload = await postJson(`/v1/music/media/${encodeURIComponent(id)}/playback-ticket`, {})
    const playback = payload?.playback && typeof payload.playback === 'object' ? payload.playback : null
    const url = String(playback?.url || '')
    if (mediaId(playback?.mediaId) !== id || !playbackPathPattern.test(url)) throw new Error('Playback ticket response is invalid')
    return url
  }

  async function ensureQueued(id) {
    if (state.queue.some((row) => mediaId(row?.track?.mediaId) === id)) return
    const payload = await postJson('/v1/music/queue', { mediaIds: [id] })
    state.queue = Array.isArray(payload.queue) ? payload.queue : state.queue
  }

  function stopAudio({ save = true } = {}) {
    if (save) void queueProgress({ force: true })
    const audio = state.audio
    if (!audio) return
    try { audio.pause() } catch (_) {}
    audio.removeAttribute('src')
    audio.removeAttribute('data-media-id')
    try { audio.load() } catch (_) {}
  }

  async function prepareSong(song, { autoplay = true, incrementPlay = true, resume = true, updatePlayer = true } = {}) {
    const id = mediaId(song?.mediaId)
    if (!id || state.loading) return
    state.loading = true
    renderQueue()
    setStatus('Preparing secure local audio…')
    try {
      if (updatePlayer) {
        const playerPayload = await postJson('/v1/music/player', { currentMediaId: id })
        state.player = playerPayload.player || state.player
      }
      if (incrementPlay) {
        const statePayload = await postJson(`/v1/music/songs/${encodeURIComponent(id)}/state`, { incrementPlay: true })
        if (statePayload.song) song = statePayload.song
      }
      const url = await issuePlayback(id)
      state.currentSong = song
      state.player.currentMediaId = id
      const audio = state.audio
      if (!audio) throw new Error('Music player surface is unavailable')
      stopAudio({ save: true })
      const startSeconds = resume ? Math.max(0, Number(song.lastPosition) || 0) : 0
      state.lastSavedSeconds = startSeconds
      state.lastQueuedSeconds = startSeconds
      audio.dataset.mediaId = id
      audio.src = url
      audio.preload = 'metadata'
      const desiredVolume = Math.max(0, Math.min(Number(state.player.volume ?? 1), 1))
      audio.volume = desiredVolume
      audio.addEventListener('loadedmetadata', () => {
        if (mediaId(audio.dataset.mediaId) !== id || !startSeconds || !Number.isFinite(audio.duration) || audio.duration <= 0) return
        audio.currentTime = Math.min(startSeconds, Math.max(0, audio.duration - 0.25))
      }, { once: true })
      audio.load()
      renderPlayer()
      void loadLyrics(song)
      if (autoplay) {
        try {
          await audio.play()
          setStatus(`${song.title || 'Track'} · playing locally`, 'success')
        } catch {
          setStatus('Player is ready. Press play to begin.')
        }
      } else {
        setStatus(`${song.title || 'Track'} · ready at ${formatDuration(startSeconds)}`)
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to start music playback', 'error')
      showError(error instanceof Error ? error.message : 'Unable to start music playback')
    } finally {
      state.loading = false
      renderQueue()
    }
  }

  async function playFromLibrary(id) {
    const song = state.songs.find((item) => mediaId(item.mediaId) === id)
    if (!song) return
    try {
      await ensureQueued(id)
      await prepareSong(song, { autoplay: true, incrementPlay: true, resume: true, updatePlayer: true })
      renderQueue()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to queue track', 'error')
    }
  }

  async function navigate(direction) {
    if (state.loading || !['previous', 'next'].includes(direction)) return
    state.loading = true
    renderQueue()
    try {
      await queueProgress({ force: true })
      const payload = await postJson(`/v1/music/player/${direction}`, {})
      state.player = payload.player || state.player
      const song = payload.song
      if (!payload.moved && payload.boundary) {
        setStatus(direction === 'next' ? 'End of queue.' : 'Start of queue.')
        return
      }
      if (song) await prepareSong(song, { autoplay: true, incrementPlay: true, resume: true, updatePlayer: false })
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Navigation failed', 'error')
    } finally {
      state.loading = false
      renderQueue()
    }
  }

  function progressSnapshot() {
    const audio = state.audio
    const id = mediaId(state.player.currentMediaId)
    if (!audio || !id || mediaId(audio.dataset.mediaId) !== id) return null
    const seconds = Math.max(0, Number(audio.currentTime) || 0)
    return { id, seconds }
  }

  function queueProgress({ force = false, keepalive = false } = {}) {
    const snapshot = progressSnapshot()
    if (!snapshot) return Promise.resolve(false)
    const distance = Math.abs(snapshot.seconds - state.lastQueuedSeconds)
    if (!force && distance < PROGRESS_INTERVAL_SECONDS) return Promise.resolve(false)
    state.lastQueuedSeconds = snapshot.seconds

    const write = async () => {
      try {
        const response = await fetch('/v1/music/player/seek', {
          method: 'POST',
          headers: authHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ positionSeconds: snapshot.seconds }),
          cache: 'no-store',
          keepalive: Boolean(keepalive),
        })
        const payload = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(payload.error || `Seek save failed (${response.status})`)
        if (mediaId(state.player.currentMediaId) === snapshot.id) state.lastSavedSeconds = snapshot.seconds
        return true
      } catch {
        if (mediaId(state.player.currentMediaId) === snapshot.id) state.lastQueuedSeconds = state.lastSavedSeconds
        return false
      }
    }

    if (keepalive) return write()
    state.saveChain = state.saveChain.catch(() => false).then(write)
    return state.saveChain
  }

  async function updateFavorite(id) {
    const song = state.songs.find((item) => mediaId(item.mediaId) === id)
    if (!song) return
    try {
      const payload = await postJson(`/v1/music/songs/${encodeURIComponent(id)}/state`, { favorite: !Boolean(song.favorite) })
      if (payload.song) Object.assign(song, payload.song)
      renderSongs()
      setStatus(song.favorite ? 'Added to favorites.' : 'Removed from favorites.', 'success')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Favorite update failed', 'error')
    }
  }

  async function enqueueSong(id) {
    try {
      const payload = await postJson('/v1/music/queue', { mediaIds: [id] })
      state.queue = Array.isArray(payload.queue) ? payload.queue : state.queue
      renderQueue()
      setStatus(payload.added ? 'Added to queue.' : 'Track is already in the queue.', 'success')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Queue update failed', 'error')
    }
  }

  async function removeQueueItem(queueId) {
    if (!/^[a-f0-9]{32}$/.test(String(queueId || ''))) return
    try {
      await postJson(`/v1/music/queue/${encodeURIComponent(queueId)}/delete`, {})
      state.queue = state.queue.filter((row) => row.id !== queueId)
      renderQueue()
      setStatus('Removed from queue.', 'success')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to remove queue item', 'error')
    }
  }

  async function clearQueue() {
    try {
      const payload = await postJson('/v1/music/queue/clear', {})
      state.queue = Array.isArray(payload.queue) ? payload.queue : []
      renderQueue()
      setStatus('Queue cleared.', 'success')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Unable to clear queue', 'error')
    }
  }

  async function updatePlayerOptions(payload) {
    try {
      const result = await postJson('/v1/music/player', payload)
      state.player = result.player || state.player
      renderPlayer()
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Player option update failed', 'error')
    }
  }

  async function syncMusic() {
    $('musicSyncButton').disabled = true
    setStatus('Syncing Music Library…')
    try {
      await postJson('/v1/music/sync', {})
      await loadMusic({ prepareCurrent: false })
      setStatus('Music Library synced.', 'success')
    } catch (error) {
      setStatus(error instanceof Error ? error.message : 'Music sync failed', 'error')
    } finally {
      $('musicSyncButton').disabled = false
    }
  }

  function bindSurfaceEvents() {
    $('musicSearchForm')?.addEventListener('submit', (event) => {
      event.preventDefault()
      state.query = $('musicSearch').value.trim()
      state.favoritesOnly = Boolean($('musicFavoritesOnly').checked)
      void loadMusic({ prepareCurrent: false })
    })
    $('musicClearSearch')?.addEventListener('click', () => {
      $('musicSearch').value = ''
      $('musicFavoritesOnly').checked = false
      state.query = ''
      state.favoritesOnly = false
      void loadMusic({ prepareCurrent: false })
    })
    $('musicSyncButton')?.addEventListener('click', () => void syncMusic())
    $('musicRefreshButton')?.addEventListener('click', () => void loadMusic({ prepareCurrent: false }))
    $('musicPrevious')?.addEventListener('click', () => void navigate('previous'))
    $('musicNext')?.addEventListener('click', () => void navigate('next'))
    $('musicClearQueue')?.addEventListener('click', () => void clearQueue())
    $('musicRepeat')?.addEventListener('change', () => void updatePlayerOptions({ repeatMode: $('musicRepeat').value }))
    $('musicShuffle')?.addEventListener('change', () => void updatePlayerOptions({ shuffle: Boolean($('musicShuffle').checked) }))
    $('musicVolume')?.addEventListener('input', () => {
      const value = Math.max(0, Math.min(Number($('musicVolume').value) || 0, 1))
      if (state.audio) state.audio.volume = value
      window.clearTimeout(state.volumeTimer)
      state.volumeTimer = window.setTimeout(() => void updatePlayerOptions({ volume: value }), 180)
    })

    const audio = state.audio
    if (audio) {
      audio.addEventListener('play', () => {
        $('musicPlayerState').textContent = 'Playing'
        setStatus(`${state.currentSong?.title || 'Track'} · playing locally`, 'success')
      })
      audio.addEventListener('pause', () => {
        if (audio.ended) return
        $('musicPlayerState').textContent = state.currentSong ? 'Paused' : 'Idle'
        void queueProgress({ force: true }).then((saved) => {
          if (saved && audio.paused && !audio.ended) setStatus('Paused · position saved.')
        })
      })
      audio.addEventListener('timeupdate', () => void queueProgress())
      audio.addEventListener('seeked', () => void queueProgress({ force: true }))
      audio.addEventListener('ended', async () => {
        await queueProgress({ force: true })
        if (String(state.player.repeatMode || 'off') === 'one') {
          audio.currentTime = 0
          state.lastSavedSeconds = 0
          state.lastQueuedSeconds = 0
          try { await audio.play() } catch (_) {}
          return
        }
        void navigate('next')
      })
      audio.addEventListener('error', () => setStatus('Playback stopped because the local audio stream became unavailable.', 'error'))
    }
  }

  document.addEventListener('click', (event) => {
    const target = event.target
    if (!(target instanceof Element)) return
    if (target.closest('[data-music-view]')) {
      void showMusicView()
      return
    }
    if (target.closest('[data-view], [data-ops-view]')) closeMusicView()

    const play = target.closest('[data-music-play]')
    if (play) void playFromLibrary(mediaId(play.dataset.musicPlay))
    const favorite = target.closest('[data-music-favorite]')
    if (favorite) void updateFavorite(mediaId(favorite.dataset.musicFavorite))
    const enqueue = target.closest('[data-music-enqueue]')
    if (enqueue) void enqueueSong(mediaId(enqueue.dataset.musicEnqueue))
    const queuePlay = target.closest('[data-music-queue-play]')
    if (queuePlay) {
      const id = mediaId(queuePlay.dataset.musicQueuePlay)
      const row = state.queue.find((item) => mediaId(item?.track?.mediaId) === id)
      if (row?.track) void prepareSong(row.track, { autoplay: true, incrementPlay: true, resume: true, updatePlayer: true })
    }
    const remove = target.closest('[data-music-queue-remove]')
    if (remove) void removeQueueItem(remove.dataset.musicQueueRemove)
  })

  document.addEventListener('DOMContentLoaded', installSurface)
  $('refreshButton')?.addEventListener('click', () => {
    if (!$('musicView')?.classList.contains('is-hidden')) void loadMusic({ prepareCurrent: false })
  })

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') void queueProgress({ force: true, keepalive: true })
  })

  window.addEventListener('beforeunload', () => {
    window.clearTimeout(state.volumeTimer)
    void queueProgress({ force: true, keepalive: true })
  })
})()
