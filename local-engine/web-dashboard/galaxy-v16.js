/* Galaxy Local Engine V1.6 modern workbench bundle.
   Source layers consolidated for the official repository sync. */

/* ===== galaxy-redesign.js ===== */
(() => {
  'use strict';

  const pageMeta = {
    dashboard: ['快速下载', '粘贴媒体链接，选择质量与登录状态，然后交给本地引擎处理。'],
    downloads: ['下载队列', '集中查看进度、速度、失败任务和批量控制。'],
    library: ['媒体库', '检索已完成的本地媒体，并同步文件可用状态。'],
    transcript: ['字幕与转写', '搜索、整理并导出已索引的字幕与转写内容。'],
    ai: ['AI 工具', '管理本地 AI 任务、Provider 与提示词。'],
    subscriptions: ['订阅监控', '持续跟踪频道与播放列表，并按规则筛选新内容。']
  };

  const title = document.getElementById('viewTitle');
  const subtitle = document.getElementById('pageSubtitle');

  const syncPageMeta = (key) => {
    const item = pageMeta[key];
    if (!item) return;
    if (title) title.textContent = item[0];
    if (subtitle) subtitle.textContent = item[1];
  };

  document.addEventListener('click', (event) => {
    const nav = event.target.closest('[data-view], [data-ops-view]');
    if (!nav) return;
    const key = nav.dataset.view || nav.dataset.opsView;
    requestAnimationFrame(() => syncPageMeta(key));
  });

  document.body.classList.add('galaxy-first-paint');
  window.setTimeout(() => document.body.classList.remove('galaxy-first-paint'), 700);
  syncPageMeta('dashboard');
})();
;

/* ===== galaxy-v11.js ===== */
(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const sleep = (ms) => new Promise((resolve) => window.setTimeout(resolve, ms));

  function toast(message, tone = '') {
    let stack = document.querySelector('.galaxy-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'galaxy-toast-stack';
      stack.setAttribute('aria-live', 'polite');
      document.body.appendChild(stack);
    }
    const item = document.createElement('div');
    item.className = `galaxy-toast ${tone}`.trim();
    item.textContent = message;
    stack.appendChild(item);
    window.setTimeout(() => item.remove(), 3600);
  }

  function setQuickStatus(message = '', tone = '') {
    const status = $('quickInlineStatus');
    if (!status) return;
    status.textContent = message;
    if (tone) status.dataset.tone = tone; else delete status.dataset.tone;
  }

  function normalizePublicUrl(value) {
    const trimmed = String(value || '').trim();
    let url;
    try { url = new URL(trimmed); } catch { return null; }
    if (!['http:', 'https:'].includes(url.protocol)) return null;
    if (url.username || url.password) return null;
    return url.toString();
  }

  function buildProtocolUrl(sourceUrl) {
    const quality = $('quickVideoQuality')?.value || 'best';
    const browser = $('quickBrowser')?.value || 'none';
    const includeAudio = $('quickIncludeAudio')?.checked !== false;
    const subtitle = $('quickSubtitle')?.checked === true;
    const cover = $('quickCover')?.checked === true;
    const params = new URLSearchParams({
      url: sourceUrl,
      video: quality,
      audio: 'best',
      include_audio: includeAudio ? '1' : '0',
      subtitle: subtitle ? '1' : '0',
      subtitle_lang: 'zh-Hans',
      cover: cover ? '1' : '0',
      browser,
    });
    return `galaxy-downloader://download?${params.toString()}`;
  }

  async function pasteFromClipboard() {
    try {
      const value = await navigator.clipboard.readText();
      if (!value) {
        setQuickStatus('剪贴板里没有可用链接。', 'error');
        return;
      }
      $('quickSourceUrl').value = value.trim();
      $('quickSourceUrl').focus();
      setQuickStatus('已从剪贴板粘贴。', 'success');
    } catch {
      setQuickStatus('浏览器未授予剪贴板权限，请直接 Ctrl+V。', 'error');
    }
  }

  async function submitQuickDownload(event) {
    event.preventDefault();
    const input = $('quickSourceUrl');
    const button = $('quickDownloadButton');
    const sourceUrl = normalizePublicUrl(input?.value);
    if (!sourceUrl) {
      setQuickStatus('请输入有效的 http / https 公网链接。', 'error');
      input?.focus();
      return;
    }

    const protocolUrl = buildProtocolUrl(sourceUrl);
    if (button) button.disabled = true;
    setQuickStatus('正在交给 Galaxy Local Engine…');
    try {
      const launcher = document.createElement('a');
      launcher.href = protocolUrl;
      launcher.style.display = 'none';
      launcher.setAttribute('aria-hidden', 'true');
      document.body.appendChild(launcher);
      launcher.click();
      launcher.remove();
      setQuickStatus('任务已提交；系统若询问是否打开 Galaxy，请允许。', 'success');
      toast('下载任务已发送到本地引擎。', 'success');
      await sleep(900);
      document.querySelector('[data-view="downloads"]')?.click();
      $('refreshButton')?.click();
    } catch {
      setQuickStatus('未能调用本地协议，请确认已运行 install.cmd。', 'error');
      toast('无法调用 Galaxy 本地协议。', 'error');
    } finally {
      if (button) button.disabled = false;
    }
  }

  function upgradeGalleryNavigation() {
    const button = document.querySelector('[data-gallery-view="gallery-dl"]');
    if (!button) return;
    button.innerHTML = `
      <svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M4 5.5A1.5 1.5 0 0 1 5.5 4h13A1.5 1.5 0 0 1 20 5.5v13a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 18.5v-13Z"/><circle cx="9" cy="9" r="1.5"/><path d="m6.5 17 4-4 2.5 2.5 2-2 2.5 3.5"/></svg>
      <span class="nav-text">原图 / 图集</span>`;
    const labels = document.querySelectorAll('.sidebar .nav-label');
    const automation = Array.from(labels).find((node) => node.textContent.trim() === '自动化');
    if (automation && button.nextElementSibling !== automation) automation.insertAdjacentElement('beforebegin', button);
  }

  function translateGallerySurface() {
    const map = {
      galleryMetricTool: ['工具'], galleryMetricVersion: ['版本'], galleryMetricActive: ['进行中'], galleryMetricQueued: ['等待中'], galleryMetricCompleted: ['已保存'],
      galleryRefreshButton: ['刷新'], gallerySubmitButton: ['添加下载'], galleryToolCheck: ['检查更新'], galleryToolInstall: ['安装'], galleryToolUpdate: ['更新'], galleryToolRemove: ['移除'],
    };
    for (const [id, [text]] of Object.entries(map)) if ($(id)) $(id).textContent = text;
    const title = document.querySelector('.gallery-submit-panel .panel-header h2');
    if (title) title.textContent = '原图 / 图集下载';
    const desc = document.querySelector('.gallery-submit-panel .panel-header p');
    if (desc) desc.textContent = '通过受管 gallery-dl 从公开网页抓取原图、图集与作品页资源。';
    const toolTitle = document.querySelector('.gallery-tool-panel .panel-header h2');
    if (toolTitle) toolTitle.textContent = '图集引擎';
    const jobsTitle = document.querySelector('.gallery-jobs-panel .panel-header h2');
    if (jobsTitle) jobsTitle.textContent = '图集任务';

    const labels = {
      gallerySourceUrl: ['来源链接', 'https://example.com/gallery'],
      galleryOutputDirectory: ['输出子目录', '产品图/项目名'],
      galleryMaxFiles: ['最多文件数', ''],
      galleryRateLimit: ['限速 MiB/s · 可选', '不限速'],
      galleryDateAfter: ['起始日期', ''],
      galleryDateBefore: ['结束日期', ''],
    };
    for (const [id, [label, placeholder]] of Object.entries(labels)) {
      const control = $(id);
      if (!control) continue;
      const field = control.closest('.field');
      const labelNode = field?.querySelector(':scope > span');
      if (labelNode) labelNode.textContent = label;
      if (placeholder) control.placeholder = placeholder;
    }
    const archive = document.querySelector('.gallery-archive-option strong');
    const resume = document.querySelector('.gallery-resume-option strong');
    if (archive) archive.textContent = '跳过已下载';
    if (resume) resume.textContent = '断点续传';
  }

  function openGallery() {
    const button = document.querySelector('[data-gallery-view="gallery-dl"]');
    if (!button) {
      toast('当前引擎未加载图集下载模块。', 'error');
      return;
    }
    button.click();
  }

  function galleryPageMeta() {
    const button = document.querySelector('[data-gallery-view="gallery-dl"]');
    if (!button) return;
    button.addEventListener('click', () => {
      window.requestAnimationFrame(() => {
        if ($('viewTitle')) $('viewTitle').textContent = '原图 / 图集';
        if ($('pageSubtitle')) $('pageSubtitle').textContent = '批量抓取网页原图、图集，并由受管 gallery-dl 处理归档与续传。';
      });
    });
  }

  function installShortcuts() {
    document.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'l') {
        event.preventDefault();
        document.querySelector('[data-view="dashboard"]')?.click();
        window.requestAnimationFrame(() => $('quickSourceUrl')?.focus());
      }
    });
  }


  function organizeDynamicNavigation() {
    const nav = document.querySelector('.sidebar nav');
    if (!nav) return;
    let systemLabel = nav.querySelector('[data-v11-system-label]');
    if (!systemLabel) {
      systemLabel = document.createElement('p');
      systemLabel.className = 'nav-label';
      systemLabel.dataset.v11SystemLabel = 'true';
      systemLabel.textContent = '系统';
      nav.appendChild(systemLabel);
    }

    const plugin = nav.querySelector('[data-plugin-view="plugins"]');
    if (plugin) {
      plugin.innerHTML = `<svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path d="M9 3h6v4h4v6h-4v4H9v-4H5V7h4V3Z"/><path d="M9 7h6v6H9z"/></svg><span class="nav-text">插件</span>`;
      nav.appendChild(plugin);
    }
    const settings = nav.querySelector('[data-settings-view="settings"]');
    if (settings) {
      settings.innerHTML = `<svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1.1V21H9.6v-.1A1.7 1.7 0 0 0 8.2 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 3.8 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1.1-.4H2V9.6h.1A1.7 1.7 0 0 0 3.8 8.2a1.7 1.7 0 0 0-.34-1.88L3.4 6.26l2.83-2.83.06.06A1.7 1.7 0 0 0 8.2 3.8a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1.1V2h4v.1A1.7 1.7 0 0 0 15 3.8a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 8.2a1.7 1.7 0 0 0 .6 1 1.7 1.7 0 0 0 1.1.4h.1v4h-.1A1.7 1.7 0 0 0 19.4 15Z"/></svg><span class="nav-text">设置</span>`;
      nav.appendChild(settings);
    }
  }

  function dynamicPageMeta() {
    document.addEventListener('click', (event) => {
      const plugin = event.target.closest('[data-plugin-view="plugins"]');
      const settings = event.target.closest('[data-settings-view="settings"]');
      if (plugin) window.requestAnimationFrame(() => {
        if ($('viewTitle')) $('viewTitle').textContent = '插件';
        if ($('pageSubtitle')) $('pageSubtitle').textContent = '管理本地插件、能力权限与更新。';
      });
      if (settings) window.requestAnimationFrame(() => {
        if ($('viewTitle')) $('viewTitle').textContent = '设置';
        if ($('pageSubtitle')) $('pageSubtitle').textContent = '查看本地引擎运行状态、安全配置与可用模块。';
      });
    });
  }

  function boot() {
    $('quickDownloadForm')?.addEventListener('submit', submitQuickDownload);
    $('quickPasteButton')?.addEventListener('click', pasteFromClipboard);
    $('quickOpenGallery')?.addEventListener('click', openGallery);
    upgradeGalleryNavigation();
    translateGallerySurface();
    galleryPageMeta();
    installShortcuts();
    organizeDynamicNavigation();
    dynamicPageMeta();
    const nav = document.querySelector('.sidebar nav');
    if (nav) new MutationObserver(() => organizeDynamicNavigation()).observe(nav, { childList: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
;

/* ===== galaxy-v12.js ===== */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);

  const SOURCES = [
    { match: /(^|\.)youtube\.com$|(^|\.)youtu\.be$/, name: 'YouTube', kind: '视频', engine: 'yt-dlp', cookie: false },
    { match: /(^|\.)vimeo\.com$/, name: 'Vimeo', kind: '视频', engine: 'yt-dlp', cookie: false },
    { match: /(^|\.)bilibili\.com$/, name: '哔哩哔哩', kind: '视频', engine: 'yt-dlp', cookie: true },
    { match: /(^|\.)tiktok\.com$|(^|\.)douyin\.com$/, name: 'TikTok / 抖音', kind: '社媒视频', engine: 'yt-dlp', cookie: true },
    { match: /(^|\.)instagram\.com$|(^|\.)facebook\.com$|(^|\.)x\.com$|(^|\.)twitter\.com$/, name: '社交媒体', kind: '社媒内容', engine: 'yt-dlp', cookie: true },
    { match: /(^|\.)homedepot\.com$/, name: 'Home Depot', kind: '商品图片 / 视频', engine: '原图 / 图集', cookie: false, gallery: true },
    { match: /(^|\.)wayfair\.com$|(^|\.)lowes\.com$|(^|\.)walmart\.com$|(^|\.)amazon\.[a-z.]+$/, name: '电商页面', kind: '商品媒体', engine: '原图 / 图集', cookie: false, gallery: true },
    { match: /(^|\.)pinterest\.[a-z.]+$|(^|\.)houzz\.com$/, name: '图片平台', kind: '图片 / 图集', engine: '原图 / 图集', cookie: true, gallery: true },
    { match: /(^|\.)alibaba\.com$|(^|\.)aliexpress\.com$|(^|\.)made-in-china\.com$/, name: 'B2B / 电商页面', kind: '商品媒体', engine: '原图 / 图集', cookie: true, gallery: true },
  ];

  function parseUrl(value) {
    try {
      const url = new URL(String(value || '').trim());
      if (!['http:', 'https:'].includes(url.protocol)) return null;
      return url;
    } catch { return null; }
  }

  function detectSource(url) {
    const host = url.hostname.toLowerCase().replace(/^www\./, '');
    const directImage = /\.(?:jpe?g|png|webp|avif|gif)(?:$|\?)/i.test(url.href);
    const directVideo = /\.(?:mp4|webm|mov|m4v|m3u8|mpd)(?:$|\?)/i.test(url.href);
    if (directImage) return { name: host, kind: '直接图片', engine: '原图 / 图集', gallery: true, cookie: false };
    if (directVideo) return { name: host, kind: '直接媒体', engine: 'yt-dlp', gallery: false, cookie: false };
    return SOURCES.find((item) => item.match.test(host)) || { name: host, kind: '网页媒体', engine: '自动识别', gallery: false, cookie: false };
  }

  function updateSourceInsight() {
    const url = parseUrl($('quickSourceUrl')?.value);
    const insight = $('quickSourceInsight');
    if (!insight) return;
    if (!url) {
      insight.classList.add('is-hidden');
      updatePlan();
      return;
    }
    const source = detectSource(url);
    insight.classList.remove('is-hidden');
    if ($('quickSourceInitial')) $('quickSourceInitial').textContent = (source.name || '?').trim().slice(0, 1).toUpperCase();
    if ($('quickSourceName')) $('quickSourceName').textContent = source.name;
    if ($('quickSourceHost')) $('quickSourceHost').textContent = `${url.hostname} · ${source.kind}`;
    if ($('quickSourceEngine')) $('quickSourceEngine').textContent = source.engine;
    if ($('quickSourceCookie')) {
      $('quickSourceCookie').textContent = source.cookie ? '登录态可能有帮助' : '通常无需登录';
      $('quickSourceCookie').classList.toggle('recommended', source.cookie);
    }
    const galleryButton = $('quickSourceGallery');
    if (galleryButton) {
      galleryButton.hidden = !source.gallery;
      galleryButton.textContent = source.gallery ? '建议使用原图 / 图集' : '';
    }
    updatePlan(source);
  }

  function labelForSelect(id) {
    const select = $(id);
    return select?.selectedOptions?.[0]?.textContent?.trim() || '—';
  }

  function updatePlan(sourceOverride) {
    const url = parseUrl($('quickSourceUrl')?.value);
    const source = sourceOverride || (url ? detectSource(url) : null);
    const pieces = [];
    pieces.push(source?.gallery ? '原图 / 图集优先' : labelForSelect('quickVideoQuality'));
    const browser = $('quickBrowser')?.value || 'none';
    pieces.push(browser === 'none' ? '不读取 Cookie' : `${labelForSelect('quickBrowser')} Cookie`);
    if ($('quickIncludeAudio')?.checked) pieces.push('合并最佳音频');
    if ($('quickSubtitle')?.checked) pieces.push('保存字幕');
    if ($('quickCover')?.checked) pieces.push('保存封面');
    const target = $('quickPlanCopy');
    if (target) {
      target.innerHTML = `<strong>本次下载</strong>${pieces.map((text) => `<span class="quick-plan-dot" aria-hidden="true"></span><span>${escapeHtml(text)}</span>`).join('')}`;
    }
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  }

  function installDownloadFilter() {
    const body = $('downloadsBody');
    const search = $('downloadFilterSearch');
    const status = $('downloadFilterStatus');
    const meta = $('downloadFilterMeta');
    if (!body || !search || !status) return;

    const apply = () => {
      const q = search.value.trim().toLowerCase();
      const s = status.value;
      const rows = Array.from(body.querySelectorAll('tr'));
      let visible = 0;
      for (const row of rows) {
        if (row.querySelector('.empty')) { row.hidden = false; continue; }
        const state = row.querySelector('.state')?.dataset.state || '';
        const text = row.textContent.toLowerCase();
        const show = (!q || text.includes(q)) && (!s || state === s);
        row.hidden = !show;
        if (show) visible += 1;
      }
      if (meta) meta.textContent = q || s ? `显示 ${visible} 项` : `${rows.filter((r) => !r.querySelector('.empty')).length} 项`;
    };
    search.addEventListener('input', apply);
    status.addEventListener('change', apply);
    new MutationObserver(apply).observe(body, { childList: true, subtree: true });
    apply();
  }

  function translateResidualEnglish() {
    const replacements = [
      ['#aiProviderReady', (el) => { if (/ready/i.test(el.textContent)) el.textContent = el.textContent.replace(/ready/ig, '可用'); }],
      ['#aiQueueMeta', (el) => { el.textContent = el.textContent.replace(/active/ig,'进行中').replace(/waiting/ig,'等待中'); }],
      ['#aiHistoryMeta', (el) => { if (/recent immutable runs/i.test(el.textContent)) el.textContent = '最近运行记录'; }],
      ['#transcriptSpeaker', (el) => { if (el.placeholder === 'Optional') el.placeholder = '可选'; }],
    ];
    replacements.forEach(([selector, fn]) => { const el = document.querySelector(selector); if (el) fn(el); });
    document.querySelectorAll('.ops-view .metric small').forEach((el) => {
      const map = {'AI tasks':'AI 任务','queued tasks':'等待任务','templates':'模板','recent runs':'最近运行','subscriptions':'订阅','scheduled':'已计划','enabled':'已启用','last check':'最近检查','tracked entries':'跟踪项目'};
      const key = el.textContent.trim(); if (map[key]) el.textContent = map[key];
    });
    document.querySelectorAll('[placeholder="comma separated"]').forEach((el) => el.placeholder = '用逗号分隔');
    document.querySelectorAll('[placeholder="Required for text tasks"]').forEach((el) => el.placeholder = '文本任务必填');
    document.querySelectorAll('[placeholder="Required only when no Prompt is selected"]').forEach((el) => el.placeholder = '未选择提示词时必填');
  }

  function boot() {
    const input = $('quickSourceUrl');
    if (input) {
      input.addEventListener('input', updateSourceInsight);
      input.addEventListener('change', updateSourceInsight);
    }
    ['quickVideoQuality','quickBrowser','quickIncludeAudio','quickSubtitle','quickCover'].forEach((id) => $(id)?.addEventListener('change', () => updatePlan()));
    $('quickSourceGallery')?.addEventListener('click', () => $('quickOpenGallery')?.click());
    installDownloadFilter();
    translateResidualEnglish();
    updateSourceInsight();
    updatePlan();
    window.setTimeout(translateResidualEnglish, 350);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
;

/* ===== galaxy-v13.js ===== */
(() => {
  'use strict';
  const KEY = 'galaxy.ui.theme';
  const THEMES = new Set(['obsidian', 'titanium', 'midnight']);
  const labels = { obsidian: '黑曜石 · 青瓷', titanium: '钛灰 · 雾蓝', midnight: '极夜 · 矿绿' };

  function getTheme() {
    try {
      const value = localStorage.getItem(KEY);
      return THEMES.has(value) ? value : 'obsidian';
    } catch { return 'obsidian'; }
  }

  function applyTheme(theme, persist = true) {
    const next = THEMES.has(theme) ? theme : 'obsidian';
    document.documentElement.dataset.gleTheme = next;
    if (persist) {
      try { localStorage.setItem(KEY, next); } catch {}
    }
    document.querySelectorAll('[data-gle-theme-option]').forEach((card) => {
      const selected = card.dataset.gleThemeOption === next;
      card.classList.toggle('is-selected', selected);
      card.setAttribute('aria-pressed', selected ? 'true' : 'false');
    });
    const current = document.getElementById('appearanceCurrentTheme');
    if (current) current.textContent = labels[next] || next;
  }

  function injectAppearancePanel() {
    const view = document.getElementById('settingsView');
    if (!view || document.getElementById('appearancePanel')) return;
    const panel = document.createElement('section');
    panel.id = 'appearancePanel';
    panel.className = 'panel appearance-panel';
    panel.innerHTML = `
      <div class="panel-header">
        <div><h2>界面外观</h2><p>默认使用低饱和、高对比的专业暗色方案。主题仅保存在本机浏览器。</p></div>
        <div class="toolbar"><span class="settings-pill" id="appearanceCurrentTheme">—</span></div>
      </div>
      <div class="appearance-grid" role="group" aria-label="界面主题">
        <button class="theme-card" type="button" data-gle-theme-option="obsidian" aria-pressed="false">
          <span class="theme-preview obsidian" aria-hidden="true"></span>
          <span class="theme-card-copy"><strong>黑曜石 · 青瓷</strong><small>暖黑、象牙白、低饱和青瓷绿。默认推荐。</small></span>
          <span class="theme-check" aria-hidden="true">✓</span>
        </button>
        <button class="theme-card" type="button" data-gle-theme-option="titanium" aria-pressed="false">
          <span class="theme-preview titanium" aria-hidden="true"></span>
          <span class="theme-card-copy"><strong>钛灰 · 雾蓝</strong><small>冷调钛灰与雾蓝，偏工程软件与专业工具。</small></span>
          <span class="theme-check" aria-hidden="true">✓</span>
        </button>
        <button class="theme-card" type="button" data-gle-theme-option="midnight" aria-pressed="false">
          <span class="theme-preview midnight" aria-hidden="true"></span>
          <span class="theme-card-copy"><strong>极夜 · 矿绿</strong><small>更深的夜色背景与矿物绿，适合长时间使用。</small></span>
          <span class="theme-check" aria-hidden="true">✓</span>
        </button>
      </div>`;
    const metrics = view.querySelector(':scope > .metrics');
    if (metrics) view.insertBefore(panel, metrics);
    else view.prepend(panel);
    panel.addEventListener('click', (event) => {
      const card = event.target.closest('[data-gle-theme-option]');
      if (!card) return;
      applyTheme(card.dataset.gleThemeOption);
    });
    applyTheme(getTheme(), false);
  }

  function polishCopy() {
    const kicker = document.querySelector('.section-kicker');
    if (kicker && kicker.textContent.trim() === 'NEW DOWNLOAD') kicker.textContent = 'MEDIA CAPTURE · 媒体捕获';
    const eyebrow = document.querySelector('.eyebrow');
    if (eyebrow) eyebrow.textContent = 'GALAXY LOCAL ENGINE · DESKTOP WORKSPACE';
  }

  function replaceBrandMark() {
    const mark = document.querySelector('.brand-mark');
    if (!mark || mark.querySelector('svg')) return;
    mark.innerHTML = '<svg aria-hidden="true" fill="none" stroke="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8.25"></circle><path d="M12 6.8v8.1m0 0 3-3m-3 3-3-3"></path><path d="M7.7 17.2c1.25.95 2.68 1.43 4.3 1.43 1.63 0 3.08-.49 4.35-1.47"></path></svg>';
  }

  function boot() {
    applyTheme(getTheme(), false);
    replaceBrandMark();
    polishCopy();
    injectAppearancePanel();
    const observer = new MutationObserver(() => injectAppearancePanel());
    observer.observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot, { once: true });
  else boot();
})();
;

/* ===== galaxy-v14.js ===== */
(() => {
  'use strict';

  const VERSION = 1;
  const STORAGE_KEY = 'galaxy.skin.v1';
  const LEGACY_THEME_KEY = 'galaxy.ui.theme';
  const SHARE_PREFIX = 'galaxy-skin-v1:';

  const BASE_THEME_LABELS = {
    obsidian: '黑曜石',
    titanium: '钛灰',
    midnight: '极夜'
  };

  const PRESETS = [
    {
      id: 'studio-graphite', name: 'Workbench', subtitle: '工作台 · 石墨', category: 'neutral', base: 'obsidian',
      accent: '#6F8FFF', canvas: '#121315', surface: '#161719', text: '#F1F2F4', brand: '#A7ACB5',
      radius: 5, density: 'compact', surfaceOpacity: 1, blur: 0, fontScale: 1, sidebarWidth: 218,
      fontFamily: 'system', background: { type: 'none', value: '', opacity: 0, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'obsidian-jade', name: 'Obsidian Jade', subtitle: '黑曜石 · 青瓷', category: 'green', base: 'obsidian',
      accent: '#8FB9AD', canvas: '#0D0E0F', surface: '#16181A', text: '#F2F0EA', brand: '#C6B58A',
      radius: 9, density: 'standard', surfaceOpacity: 0.96, blur: 18, fontScale: 1, sidebarWidth: 232,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 68% 14%, rgba(92,129,116,.16), transparent 36%), linear-gradient(145deg, #0d0e0f 0%, #101312 62%, #0d0e0f 100%)', opacity: 0.42, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'titanium-fog', name: 'Titanium Fog', subtitle: '钛灰 · 雾蓝', category: 'blue', base: 'titanium',
      accent: '#94A8BF', canvas: '#0E1013', surface: '#171A1F', text: '#F1F3F5', brand: '#C4C7CA',
      radius: 9, density: 'standard', surfaceOpacity: 0.96, blur: 18, fontScale: 1, sidebarWidth: 232,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 72% 12%, rgba(96,126,157,.18), transparent 38%), linear-gradient(150deg, #0d0f12, #12161b 58%, #0d0f12)', opacity: 0.44, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'carbon-copper', name: 'Carbon Copper', subtitle: '碳黑 · 暖铜', category: 'warm', base: 'obsidian',
      accent: '#B99072', canvas: '#0D0C0B', surface: '#181614', text: '#F2EEE8', brand: '#C8AA88',
      radius: 10, density: 'standard', surfaceOpacity: 0.95, blur: 16, fontScale: 1, sidebarWidth: 232,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 74% 18%, rgba(174,112,72,.16), transparent 34%), linear-gradient(150deg, #0d0c0b, #15110f 62%, #0e0d0c)', opacity: 0.46, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'plum-ink', name: 'Plum Ink', subtitle: '墨紫 · 银灰', category: 'purple', base: 'midnight',
      accent: '#A795AF', canvas: '#0D0B10', surface: '#17141A', text: '#F1EEF2', brand: '#BBB1C0',
      radius: 11, density: 'standard', surfaceOpacity: 0.95, blur: 18, fontScale: 1, sidebarWidth: 232,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 66% 10%, rgba(128,93,143,.18), transparent 38%), linear-gradient(145deg, #0d0b10, #15111a 60%, #0e0c11)', opacity: 0.48, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'arctic-ink', name: 'Arctic Ink', subtitle: '冰川 · 深墨', category: 'blue', base: 'titanium',
      accent: '#88B5BE', canvas: '#091013', surface: '#121A1E', text: '#EFF4F4', brand: '#AABEC2',
      radius: 10, density: 'standard', surfaceOpacity: 0.94, blur: 20, fontScale: 1, sidebarWidth: 232,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 74% 8%, rgba(77,142,154,.20), transparent 40%), linear-gradient(145deg, #091013, #0f171b 55%, #0a1013)', opacity: 0.5, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'moss-studio', name: 'Moss Studio', subtitle: '苔藓 · 岩灰', category: 'green', base: 'midnight',
      accent: '#91A681', canvas: '#0D0F0C', surface: '#161A15', text: '#F0F1EC', brand: '#AEB39C',
      radius: 12, density: 'spacious', surfaceOpacity: 0.95, blur: 18, fontScale: 1, sidebarWidth: 238,
      fontFamily: 'system', background: { type: 'gradient', value: 'radial-gradient(circle at 70% 13%, rgba(111,132,91,.18), transparent 38%), linear-gradient(145deg, #0d0f0c, #131812 58%, #0d0f0c)', opacity: 0.45, blur: 0, zoom: 100, position: 'center' }
    },
    {
      id: 'mono-pro', name: 'Mono Pro', subtitle: '纯黑 · 冷白', category: 'mono', base: 'obsidian',
      accent: '#D6D8D7', canvas: '#090A0A', surface: '#131515', text: '#F4F4F2', brand: '#C9CBCA',
      radius: 7, density: 'compact', surfaceOpacity: 0.98, blur: 10, fontScale: 0.98, sidebarWidth: 220,
      fontFamily: 'system', background: { type: 'none', value: '', opacity: 0.12, blur: 0, zoom: 100, position: 'center' }
    }
  ];

  const BACKGROUNDS = [
    { id: 'none', name: '无背景', value: '' },
    { id: 'sumi', name: '墨迹', value: 'radial-gradient(circle at 72% 12%, rgba(128,138,133,.16), transparent 38%), radial-gradient(circle at 22% 78%, rgba(83,95,91,.10), transparent 32%), linear-gradient(145deg, #0b0c0d, #101312 58%, #0a0b0c)' },
    { id: 'mineral', name: '矿石', value: 'radial-gradient(circle at 78% 10%, rgba(106,139,132,.22), transparent 40%), radial-gradient(circle at 18% 80%, rgba(71,91,88,.12), transparent 34%), linear-gradient(145deg, #0a0d0d, #101514 58%, #0a0c0c)' },
    { id: 'ember', name: '余烬', value: 'radial-gradient(circle at 74% 12%, rgba(175,103,64,.19), transparent 36%), radial-gradient(circle at 15% 82%, rgba(102,63,47,.12), transparent 32%), linear-gradient(145deg, #0d0b0a, #16110f 60%, #0c0b0a)' },
    { id: 'aurora', name: '极光', value: 'radial-gradient(circle at 76% 8%, rgba(77,136,151,.20), transparent 38%), radial-gradient(circle at 32% 86%, rgba(117,82,136,.14), transparent 34%), linear-gradient(145deg, #090d11, #10151b 58%, #0b0d12)' },
    { id: 'linen', name: '亚麻暗纹', value: 'linear-gradient(135deg, rgba(255,255,255,.025) 25%, transparent 25%) 0 0/18px 18px, linear-gradient(315deg, rgba(255,255,255,.018) 25%, transparent 25%) 0 0/18px 18px, #0e0f10' }
  ];

  const DEFAULT_STATE = clone(PRESETS[0]);
  DEFAULT_STATE.customName = '我的皮肤';

  let state = loadState();
  let previousState = null;
  let drawer = null;
  let lastFocused = null;
  let saveTimer = null;

  function clone(value) { return JSON.parse(JSON.stringify(value)); }
  function clamp(value, min, max) { return Math.min(max, Math.max(min, Number(value))); }
  function isHex(value) { return /^#[0-9A-F]{6}$/i.test(String(value || '')); }
  function safeHex(value, fallback) { return isHex(value) ? value.toUpperCase() : fallback; }
  function hexToRgb(hex) {
    const v = safeHex(hex, '#000000').slice(1);
    return [parseInt(v.slice(0,2),16), parseInt(v.slice(2,4),16), parseInt(v.slice(4,6),16)];
  }
  function rgba(hex, alpha) { const [r,g,b] = hexToRgb(hex); return `rgba(${r}, ${g}, ${b}, ${clamp(alpha,0,1)})`; }
  function mixHex(a, b, amount) {
    const ra = hexToRgb(a), rb = hexToRgb(b), t = clamp(amount,0,1);
    const c = ra.map((v,i)=>Math.round(v+(rb[i]-v)*t));
    return `#${c.map(v=>v.toString(16).padStart(2,'0')).join('')}`.toUpperCase();
  }
  function luminance(hex) {
    const rgb = hexToRgb(hex).map(v=>v/255).map(v=>v<=0.03928?v/12.92:Math.pow((v+0.055)/1.055,2.4));
    return 0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2];
  }
  function contrast(a,b) {
    const l1=luminance(a), l2=luminance(b); return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
  }
  function normalizeState(input) {
    const base = clone(DEFAULT_STATE);
    const src = input && typeof input === 'object' ? input : {};
    const out = { ...base, ...src };
    out.version = VERSION;
    out.id = String(src.id || base.id).slice(0,64);
    out.name = String(src.name || base.name).slice(0,80);
    out.subtitle = String(src.subtitle || base.subtitle).slice(0,120);
    out.customName = String(src.customName || '我的皮肤').slice(0,80);
    out.base = ['obsidian','titanium','midnight'].includes(src.base) ? src.base : base.base;
    out.accent = safeHex(src.accent, base.accent);
    out.canvas = safeHex(src.canvas, base.canvas);
    out.surface = safeHex(src.surface, base.surface);
    out.text = safeHex(src.text, base.text);
    out.brand = safeHex(src.brand, base.brand);
    out.radius = clamp(src.radius ?? base.radius, 4, 24);
    out.density = ['compact','standard','spacious'].includes(src.density) ? src.density : base.density;
    out.surfaceOpacity = clamp(src.surfaceOpacity ?? base.surfaceOpacity, 0.62, 1);
    out.blur = clamp(src.blur ?? base.blur, 0, 36);
    out.fontScale = clamp(src.fontScale ?? base.fontScale, 0.9, 1.16);
    out.sidebarWidth = clamp(src.sidebarWidth ?? base.sidebarWidth, 206, 286);
    out.fontFamily = ['system','rounded','mono'].includes(src.fontFamily) ? src.fontFamily : 'system';
    const bg = src.background && typeof src.background === 'object' ? src.background : base.background;
    out.background = {
      type: ['none','gradient','image','url'].includes(bg.type) ? bg.type : 'none',
      value: String(bg.value || '').slice(0, 5500000),
      opacity: clamp(bg.opacity ?? 0.18, 0, 0.85),
      blur: clamp(bg.blur ?? 0, 0, 28),
      zoom: clamp(bg.zoom ?? 100, 80, 180),
      position: ['center','top','bottom','left','right'].includes(bg.position) ? bg.position : 'center'
    };
    return out;
  }
  function loadState() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) return normalizeState(JSON.parse(raw));
      const legacy = localStorage.getItem(LEGACY_THEME_KEY);
      const preset = PRESETS.find(p => p.base === legacy) || PRESETS[0];
      return normalizeState(preset);
    } catch { return normalizeState(DEFAULT_STATE); }
  }
  function scheduleSave() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); localStorage.setItem(LEGACY_THEME_KEY, state.base); } catch {}
    }, 80);
  }
  function setVar(name, value) { document.documentElement.style.setProperty(name, value); }
  function fontFamilyValue(kind) {
    if (kind === 'rounded') return '"Segoe UI Variable Display", "Segoe UI", "Microsoft YaHei UI", system-ui, sans-serif';
    if (kind === 'mono') return '"Cascadia Code", "SFMono-Regular", Consolas, "Microsoft YaHei UI", monospace';
    return '"Segoe UI Variable Text", "Segoe UI", "Microsoft YaHei UI", system-ui, -apple-system, sans-serif';
  }
  function applyState(next, options = {}) {
    const { persist = true, remember = false, announce = false } = options;
    if (remember) previousState = clone(state);
    state = normalizeState(next);
    const root = document.documentElement;
    root.dataset.gleTheme = state.base;
    root.dataset.gleSkin = state.id || 'custom';
    root.dataset.gleDensity = state.density;
    root.dataset.gleFont = state.fontFamily;

    const border = mixHex(state.surface, state.text, 0.12);
    const borderStrong = mixHex(state.surface, state.text, 0.22);
    const surface2 = mixHex(state.surface, state.text, 0.035);
    const surface3 = mixHex(state.surface, state.text, 0.07);
    const field = mixHex(state.canvas, state.surface, 0.48);
    const accentInk = luminance(state.accent) > 0.43 ? '#101413' : '#F3F5F4';
    const text2 = mixHex(state.text, state.surface, 0.22);
    const text3 = mixHex(state.text, state.surface, 0.43);
    const muted = mixHex(state.text, state.surface, 0.58);

    setVar('--gle-canvas', state.canvas);
    setVar('--gle-sidebar', mixHex(state.canvas, state.surface, 0.28));
    setVar('--gle-surface', state.surface);
    setVar('--gle-surface-2', surface2);
    setVar('--gle-surface-3', surface3);
    setVar('--gle-field', field);
    setVar('--gle-border', border);
    setVar('--gle-border-strong', borderStrong);
    setVar('--gle-text', state.text);
    setVar('--gle-text-2', text2);
    setVar('--gle-text-3', text3);
    setVar('--gle-muted', muted);
    setVar('--gle-accent', state.accent);
    setVar('--gle-accent-hover', mixHex(state.accent, state.text, 0.12));
    setVar('--gle-accent-ink', accentInk);
    setVar('--gle-accent-soft', rgba(state.accent, 0.11));
    setVar('--gle-accent-line', rgba(state.accent, 0.42));
    setVar('--gle-brand', state.brand);
    setVar('--gle-brand-soft', rgba(state.brand, 0.10));
    setVar('--gle-radius', `${state.radius}px`);
    setVar('--gle-radius-sm', `${Math.max(5, state.radius - 2)}px`);
    setVar('--gle-surface-glass', rgba(state.surface, state.surfaceOpacity));
    setVar('--gle-sidebar-glass', rgba(mixHex(state.canvas, state.surface, 0.28), Math.min(1, state.surfaceOpacity + 0.02)));
    setVar('--gle-chrome-blur', `${state.blur}px`);
    setVar('--gle-font-scale', String(state.fontScale));
    setVar('--gle-sidebar-width', `${state.sidebarWidth}px`);
    setVar('--gle-font-family', fontFamilyValue(state.fontFamily));
    setVar('--gle-wallpaper-opacity', String(state.background.opacity));
    setVar('--gle-wallpaper-blur', `${state.background.blur}px`);
    setVar('--gle-wallpaper-size', `${state.background.zoom}%`);
    setVar('--gle-wallpaper-position', state.background.position);

    let bgImage = 'none';
    if (state.background.type === 'gradient' && state.background.value) bgImage = state.background.value;
    else if ((state.background.type === 'image' || state.background.type === 'url') && state.background.value) {
      const value = state.background.value.replace(/[\n\r]/g, '');
      bgImage = `url("${value.replace(/"/g, '%22')}")`;
    }
    setVar('--gle-wallpaper-image', bgImage);

    if (persist) scheduleSave();
    syncUi();
    if (announce) toast(`已应用：${state.customName || state.subtitle || state.name}`);
  }

  function toast(message, tone = 'neutral') {
    let host = document.getElementById('skinToast');
    if (!host) {
      host = document.createElement('div'); host.id = 'skinToast'; host.className = 'skin-toast'; document.body.append(host);
    }
    host.dataset.tone = tone; host.textContent = message; host.classList.add('is-visible');
    clearTimeout(host.__timer); host.__timer = setTimeout(()=>host.classList.remove('is-visible'), 2200);
  }

  function svgIcon(name) {
    const icons = {
      palette: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 3a9 9 0 1 0 0 18h1.2a1.8 1.8 0 0 0 0-3.6h-.7a1.8 1.8 0 0 1 0-3.6H16A5 5 0 0 0 21 8.8C21 5.5 17 3 12 3Z"/><circle cx="7.5" cy="10" r="1"/><circle cx="10" cy="6.8" r="1"/><circle cx="14" cy="6.6" r="1"/><circle cx="17" cy="9" r="1"/></svg>',
      close: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="m6 6 12 12M18 6 6 18"/></svg>',
      undo: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M9 8H5v-4M5.5 7.5A8 8 0 1 1 4 15"/></svg>',
      upload: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 16V4m0 0 4 4m-4-4L8 8M5 14v5h14v-5"/></svg>',
      download: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><path d="M12 4v12m0 0 4-4m-4 4-4-4M5 20h14"/></svg>',
      copy: '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor"><rect x="8" y="8" width="11" height="11" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/></svg>'
    };
    return icons[name] || '';
  }

  function injectTopButton() {
    const actions = document.querySelector('.topbar-actions');
    if (!actions || document.getElementById('skinStudioButton')) return;
    const button = document.createElement('button');
    button.className = 'button secondary skin-studio-trigger'; button.id = 'skinStudioButton'; button.type = 'button';
    button.innerHTML = `${svgIcon('palette')}<span>皮肤</span>`;
    button.addEventListener('click', openDrawer);
    actions.prepend(button);
  }

  function drawerMarkup() {
    return `
      <div class="skin-backdrop" data-skin-close></div>
      <aside class="skin-drawer" role="dialog" aria-modal="true" aria-labelledby="skinDrawerTitle">
        <header class="skin-drawer-header">
          <div><span class="skin-eyebrow">APPEARANCE STUDIO</span><h2 id="skinDrawerTitle">皮肤工作室</h2><p>主题、布局、背景与分享都可实时预览。</p></div>
          <div class="skin-header-actions">
            <button class="skin-icon-button" id="skinUndoButton" type="button" title="撤销最近一次皮肤调整">${svgIcon('undo')}</button>
            <button class="skin-icon-button" type="button" data-skin-close aria-label="关闭">${svgIcon('close')}</button>
          </div>
        </header>
        <nav class="skin-tabs" aria-label="皮肤设置">
          <button class="skin-tab is-active" type="button" data-skin-tab="library">主题库</button>
          <button class="skin-tab" type="button" data-skin-tab="customize">自定义</button>
          <button class="skin-tab" type="button" data-skin-tab="background">背景</button>
          <button class="skin-tab" type="button" data-skin-tab="share">导入 / 分享</button>
        </nav>
        <div class="skin-scroll">
          <section class="skin-pane" data-skin-pane="library">
            <div class="skin-section-head"><div><h3>精选皮肤</h3><p>一键应用完整视觉方案，可在“自定义”继续微调。</p></div><span class="skin-count">${PRESETS.length} 套</span></div>
            <div class="skin-filter-row" role="group" aria-label="皮肤分类">
              <button class="skin-filter is-active" data-skin-filter="all" type="button">全部</button>
              <button class="skin-filter" data-skin-filter="neutral" type="button">中性</button>
              <button class="skin-filter" data-skin-filter="green" type="button">绿色</button>
              <button class="skin-filter" data-skin-filter="blue" type="button">蓝灰</button>
              <button class="skin-filter" data-skin-filter="warm" type="button">暖色</button>
              <button class="skin-filter" data-skin-filter="purple" type="button">紫灰</button>
              <button class="skin-filter" data-skin-filter="mono" type="button">黑白</button>
            </div>
            <div class="skin-library-grid" id="skinLibraryGrid"></div>
          </section>

          <section class="skin-pane is-hidden" data-skin-pane="customize">
            <div class="skin-section-head"><div><h3>视觉参数</h3><p>修改颜色、圆角、密度和字体；所有修改即时生效。</p></div><span class="skin-live-dot">实时</span></div>
            <div class="skin-controls-grid">
              ${colorControl('skinAccent','强调色','accent')}
              ${colorControl('skinCanvas','背景色','canvas')}
              ${colorControl('skinSurface','面板色','surface')}
              ${colorControl('skinText','正文色','text')}
              ${colorControl('skinBrand','品牌点缀','brand')}
            </div>
            <div class="skin-divider"></div>
            <div class="skin-control-stack">
              ${rangeControl('skinRadius','圆角','4','24','1','px')}
              ${rangeControl('skinSurfaceOpacity','面板透明度','62','100','1','%')}
              ${rangeControl('skinBlur','玻璃模糊','0','36','1','px')}
              ${rangeControl('skinFontScale','字体缩放','90','116','1','%')}
              ${rangeControl('skinSidebarWidth','侧栏宽度','206','286','2','px')}
            </div>
            <div class="skin-divider"></div>
            <div class="skin-field-group"><label>信息密度</label><div class="skin-segmented" id="skinDensity"><button type="button" data-value="compact">紧凑</button><button type="button" data-value="standard">标准</button><button type="button" data-value="spacious">宽松</button></div></div>
            <div class="skin-field-group"><label for="skinFontFamily">界面字体</label><select id="skinFontFamily"><option value="system">系统 UI</option><option value="rounded">现代圆润</option><option value="mono">等宽工作台</option></select></div>
            <div class="skin-contrast-card"><div><strong>可读性检查</strong><span id="skinContrastMeta">—</span></div><span class="skin-contrast-badge" id="skinContrastBadge">—</span></div>
          </section>

          <section class="skin-pane is-hidden" data-skin-pane="background">
            <div class="skin-section-head"><div><h3>工作区背景</h3><p>支持内置氛围、图片上传或远程图片 URL。背景不会修改下载内核。</p></div></div>
            <div class="skin-background-grid" id="skinBackgroundGrid"></div>
            <div class="skin-divider"></div>
            <div class="skin-upload-zone" id="skinUploadZone" tabindex="0">
              ${svgIcon('upload')}<div><strong>拖入图片或点击选择</strong><span>JPG / PNG / WebP，自动压缩到适合本地保存的尺寸</span></div>
              <input id="skinWallpaperFile" type="file" accept="image/png,image/jpeg,image/webp" hidden>
            </div>
            <div class="skin-field-group"><label for="skinWallpaperUrl">图片 URL</label><div class="skin-inline"><input id="skinWallpaperUrl" type="url" placeholder="https://example.com/background.jpg"><button class="skin-small-button" id="skinApplyUrl" type="button">应用</button></div></div>
            <div class="skin-control-stack">
              ${rangeControl('skinWallpaperOpacity','背景强度','0','85','1','%')}
              ${rangeControl('skinWallpaperBlur','背景模糊','0','28','1','px')}
              ${rangeControl('skinWallpaperZoom','背景缩放','80','180','1','%')}
            </div>
            <div class="skin-field-group"><label for="skinWallpaperPosition">背景位置</label><select id="skinWallpaperPosition"><option value="center">居中</option><option value="top">顶部</option><option value="bottom">底部</option><option value="left">左侧</option><option value="right">右侧</option></select></div>
            <button class="skin-secondary-button" id="skinRemoveWallpaper" type="button">移除背景</button>
          </section>

          <section class="skin-pane is-hidden" data-skin-pane="share">
            <div class="skin-section-head"><div><h3>导入与分享</h3><p>皮肤是可读 JSON 配置，不修改程序文件，可随时恢复。</p></div></div>
            <div class="skin-field-group"><label for="skinCustomName">皮肤名称</label><input id="skinCustomName" maxlength="80" value="我的皮肤"></div>
            <div class="skin-share-actions"><button class="skin-primary-button" id="skinExportFile" type="button">${svgIcon('download')}导出 .galaxyskin</button><button class="skin-secondary-button" id="skinImportFileButton" type="button">${svgIcon('upload')}导入文件</button><input id="skinImportFile" type="file" accept=".galaxyskin,application/json" hidden></div>
            <div class="skin-field-group"><label for="skinShareString">分享字符串</label><div class="skin-inline"><input id="skinShareString" spellcheck="false" readonly><button class="skin-small-button" id="skinCopyShare" type="button">${svgIcon('copy')}复制</button></div><small>分享字符串不包含本地上传的背景图片，避免内容过大。</small></div>
            <div class="skin-field-group"><label for="skinImportString">粘贴分享字符串</label><textarea id="skinImportString" rows="4" spellcheck="false" placeholder="galaxy-skin-v1:..."></textarea><button class="skin-secondary-button" id="skinImportStringButton" type="button">导入分享字符串</button></div>
            <div class="skin-divider"></div>
            <div class="skin-field-group"><label for="skinGithubUrl">GitHub / Raw 皮肤地址</label><div class="skin-inline"><input id="skinGithubUrl" type="url" placeholder="https://github.com/user/repo/blob/main/theme.galaxyskin"><button class="skin-small-button" id="skinImportGithub" type="button">获取</button></div><small>支持 GitHub blob 链接并自动转换为 raw 地址，也支持普通 HTTPS JSON 地址。</small></div>
            <div class="skin-divider"></div>
            <button class="skin-danger-ghost" id="skinResetAll" type="button">恢复默认皮肤</button>
            <p class="skin-status" id="skinShareStatus" role="status"></p>
          </section>
        </div>
        <footer class="skin-footer"><span id="skinCurrentLabel">—</span><span>仅保存在本机 · 可逆</span></footer>
      </aside>`;
  }

  function colorControl(id, label, key) {
    return `<label class="skin-color-control"><span>${label}</span><div><input id="${id}" data-skin-color="${key}" type="color"><input class="skin-hex-input" data-skin-hex="${key}" maxlength="7" spellcheck="false"></div></label>`;
  }
  function rangeControl(id, label, min, max, step, unit) {
    return `<label class="skin-range-control"><span>${label}</span><div><input id="${id}" data-skin-range type="range" min="${min}" max="${max}" step="${step}"><output for="${id}" data-unit="${unit}">—</output></div></label>`;
  }

  function injectDrawer() {
    if (document.getElementById('skinStudioRoot')) return;
    const root = document.createElement('div'); root.id = 'skinStudioRoot'; root.className = 'skin-studio-root'; root.setAttribute('aria-hidden','true'); root.innerHTML = drawerMarkup();
    document.body.append(root); drawer = root;
    buildPresetCards(); buildBackgroundCards(); bindDrawer(); syncUi();
  }

  function buildPresetCards(filter = 'all') {
    const grid = document.getElementById('skinLibraryGrid'); if (!grid) return;
    const items = PRESETS.filter(p=>filter==='all'||p.category===filter);
    grid.innerHTML = items.map(p=>{
      const colors = [p.canvas,p.surface,p.accent,p.text];
      return `<button class="skin-preset-card" type="button" data-skin-preset="${p.id}">
        <span class="skin-preset-preview" style="--p-bg:${p.canvas};--p-surface:${p.surface};--p-accent:${p.accent};--p-text:${p.text}"><i></i><b></b><em></em></span>
        <span class="skin-preset-copy"><strong>${escapeHtml(p.subtitle)}</strong><small>${escapeHtml(p.name)}</small></span>
        <span class="skin-palette-dots">${colors.map(c=>`<i style="background:${c}"></i>`).join('')}</span>
      </button>`;
    }).join('');
    syncUi();
  }

  function buildBackgroundCards() {
    const grid = document.getElementById('skinBackgroundGrid'); if (!grid) return;
    grid.innerHTML = BACKGROUNDS.map(bg=>`<button class="skin-bg-card" type="button" data-skin-background="${bg.id}" title="${bg.name}"><span style="background:${bg.value || '#111315'}"></span><strong>${bg.name}</strong></button>`).join('');
  }

  function escapeHtml(text) { return String(text).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

  function bindDrawer() {
    drawer.addEventListener('click', (event) => {
      const close = event.target.closest('[data-skin-close]'); if (close) { closeDrawer(); return; }
      const tab = event.target.closest('[data-skin-tab]'); if (tab) { setTab(tab.dataset.skinTab); return; }
      const filter = event.target.closest('[data-skin-filter]'); if (filter) {
        drawer.querySelectorAll('[data-skin-filter]').forEach(b=>b.classList.toggle('is-active',b===filter)); buildPresetCards(filter.dataset.skinFilter); return;
      }
      const presetButton = event.target.closest('[data-skin-preset]'); if (presetButton) {
        const preset = PRESETS.find(p=>p.id===presetButton.dataset.skinPreset); if (preset) { previousState=clone(state); applyState({...preset,customName:preset.subtitle},{announce:true}); } return;
      }
      const bgButton = event.target.closest('[data-skin-background]'); if (bgButton) {
        const bg = BACKGROUNDS.find(x=>x.id===bgButton.dataset.skinBackground); if (bg) { previousState=clone(state); state.background={...state.background,type:bg.id==='none'?'none':'gradient',value:bg.value}; applyState(state); } return;
      }
      const densityButton = event.target.closest('#skinDensity [data-value]'); if (densityButton) {
        previousState=clone(state); state.density=densityButton.dataset.value; state.id='custom'; state.customName='自定义皮肤'; applyState(state); return;
      }
    });

    drawer.querySelectorAll('[data-skin-color]').forEach(input=>input.addEventListener('input',()=>{
      const key=input.dataset.skinColor; state[key]=safeHex(input.value,state[key]); state.id='custom'; state.customName='自定义皮肤'; applyState(state); syncColorPair(key);
    }));
    drawer.querySelectorAll('[data-skin-hex]').forEach(input=>input.addEventListener('change',()=>{
      const key=input.dataset.skinHex; if(!isHex(input.value)){input.value=state[key];return;} state[key]=input.value.toUpperCase(); state.id='custom'; state.customName='自定义皮肤'; applyState(state); syncColorPair(key);
    }));

    const rangeMap = {
      skinRadius: ['radius', v=>Number(v), v=>`${v}px`],
      skinSurfaceOpacity: ['surfaceOpacity', v=>Number(v)/100, v=>`${Math.round(v*100)}%`],
      skinBlur: ['blur', v=>Number(v), v=>`${v}px`],
      skinFontScale: ['fontScale', v=>Number(v)/100, v=>`${Math.round(v*100)}%`],
      skinSidebarWidth: ['sidebarWidth', v=>Number(v), v=>`${v}px`],
      skinWallpaperOpacity: ['background.opacity', v=>Number(v)/100, v=>`${Math.round(v*100)}%`],
      skinWallpaperBlur: ['background.blur', v=>Number(v), v=>`${v}px`],
      skinWallpaperZoom: ['background.zoom', v=>Number(v), v=>`${v}%`]
    };
    Object.entries(rangeMap).forEach(([id,[path,parse,format]])=>{
      const el=document.getElementById(id); if(!el)return;
      el.addEventListener('input',()=>{ setPath(state,path,parse(el.value)); state.id='custom'; state.customName='自定义皮肤'; applyState(state); const out=el.parentElement.querySelector('output'); if(out)out.textContent=format(getPath(state,path)); });
    });

    const font=document.getElementById('skinFontFamily'); if(font)font.addEventListener('change',()=>{state.fontFamily=font.value;state.id='custom';state.customName='自定义皮肤';applyState(state);});
    const pos=document.getElementById('skinWallpaperPosition'); if(pos)pos.addEventListener('change',()=>{state.background.position=pos.value;state.id='custom';applyState(state);});
    const name=document.getElementById('skinCustomName'); if(name)name.addEventListener('input',()=>{state.customName=name.value.trim()||'我的皮肤';scheduleSave();syncShare();});

    const undo=document.getElementById('skinUndoButton'); if(undo)undo.addEventListener('click',()=>{if(previousState){const current=clone(state);applyState(previousState,{announce:true});previousState=current;}else toast('暂无可撤销的皮肤调整');});
    const zone=document.getElementById('skinUploadZone'); const file=document.getElementById('skinWallpaperFile');
    if(zone&&file){
      zone.addEventListener('click',()=>file.click()); zone.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();file.click();}});
      ;['dragenter','dragover'].forEach(type=>zone.addEventListener(type,e=>{e.preventDefault();zone.classList.add('is-dragging');}));
      ;['dragleave','drop'].forEach(type=>zone.addEventListener(type,e=>{e.preventDefault();zone.classList.remove('is-dragging');}));
      zone.addEventListener('drop',e=>{const f=e.dataTransfer.files&&e.dataTransfer.files[0]; if(f)handleWallpaperFile(f);});
      file.addEventListener('change',()=>{const f=file.files&&file.files[0];if(f)handleWallpaperFile(f);file.value='';});
    }
    document.getElementById('skinApplyUrl')?.addEventListener('click',()=>{const input=document.getElementById('skinWallpaperUrl');const value=input.value.trim();if(!/^https:\/\//i.test(value)){toast('请输入 HTTPS 图片地址','error');return;}previousState=clone(state);state.background={...state.background,type:'url',value};state.id='custom';applyState(state);toast('远程背景已应用');});
    document.getElementById('skinRemoveWallpaper')?.addEventListener('click',()=>{previousState=clone(state);state.background={...state.background,type:'none',value:''};state.id='custom';applyState(state);toast('背景已移除');});

    document.getElementById('skinExportFile')?.addEventListener('click',exportFile);
    document.getElementById('skinImportFileButton')?.addEventListener('click',()=>document.getElementById('skinImportFile')?.click());
    document.getElementById('skinImportFile')?.addEventListener('change',async e=>{const f=e.target.files&&e.target.files[0];if(!f)return;try{importPayload(JSON.parse(await f.text()),`文件 ${f.name}`);}catch(err){setShareStatus(`导入失败：${err.message}`,'error');}e.target.value='';});
    document.getElementById('skinCopyShare')?.addEventListener('click',copyShare);
    document.getElementById('skinImportStringButton')?.addEventListener('click',()=>{try{importPayload(parseShare(document.getElementById('skinImportString').value.trim()),'分享字符串');}catch(err){setShareStatus(`导入失败：${err.message}`,'error');}});
    document.getElementById('skinImportGithub')?.addEventListener('click',importFromUrl);
    document.getElementById('skinResetAll')?.addEventListener('click',()=>{previousState=clone(state);applyState({...PRESETS[0],customName:PRESETS[0].subtitle},{announce:true});setShareStatus('已恢复默认皮肤。','ok');});
  }

  function setPath(obj,path,value){const parts=path.split('.');let cur=obj;for(let i=0;i<parts.length-1;i++)cur=cur[parts[i]];cur[parts.at(-1)]=value;}
  function getPath(obj,path){return path.split('.').reduce((o,k)=>o?.[k],obj);}

  async function handleWallpaperFile(file) {
    if(!/^image\/(png|jpeg|webp)$/i.test(file.type)){toast('仅支持 JPG / PNG / WebP','error');return;}
    if(file.size>18*1024*1024){toast('图片超过 18 MB，请先压缩','error');return;}
    try{
      toast('正在优化背景图片…');
      const data=await compressImage(file,2560,0.86); previousState=clone(state); state.background={...state.background,type:'image',value:data};state.id='custom';state.customName='自定义皮肤';applyState(state);toast('本地背景已应用','ok');
    }catch(err){toast(`背景处理失败：${err.message}`,'error');}
  }

  function compressImage(file,maxEdge=2560,quality=.86){
    return new Promise((resolve,reject)=>{
      const img=new Image(); const url=URL.createObjectURL(file);
      img.onload=()=>{try{let w=img.naturalWidth,h=img.naturalHeight;const scale=Math.min(1,maxEdge/Math.max(w,h));w=Math.max(1,Math.round(w*scale));h=Math.max(1,Math.round(h*scale));const canvas=document.createElement('canvas');canvas.width=w;canvas.height=h;const ctx=canvas.getContext('2d',{alpha:false});ctx.drawImage(img,0,0,w,h);URL.revokeObjectURL(url);resolve(canvas.toDataURL('image/jpeg',quality));}catch(e){URL.revokeObjectURL(url);reject(e);}};
      img.onerror=()=>{URL.revokeObjectURL(url);reject(new Error('无法读取图片'));}; img.src=url;
    });
  }

  function setTab(name) {
    drawer.querySelectorAll('[data-skin-tab]').forEach(b=>b.classList.toggle('is-active',b.dataset.skinTab===name));
    drawer.querySelectorAll('[data-skin-pane]').forEach(p=>p.classList.toggle('is-hidden',p.dataset.skinPane!==name));
    if(name==='share')syncShare();
  }
  function openDrawer() {
    injectDrawer(); lastFocused=document.activeElement; drawer.classList.add('is-open'); drawer.setAttribute('aria-hidden','false'); document.body.classList.add('skin-drawer-open');
    setTimeout(()=>drawer.querySelector('.skin-tab.is-active')?.focus(),20);
  }
  function closeDrawer() {
    if(!drawer)return; drawer.classList.remove('is-open'); drawer.setAttribute('aria-hidden','true'); document.body.classList.remove('skin-drawer-open'); lastFocused?.focus?.();
  }

  function syncColorPair(key) {
    const color=drawer?.querySelector(`[data-skin-color="${key}"]`); const hex=drawer?.querySelector(`[data-skin-hex="${key}"]`); if(color)color.value=state[key];if(hex)hex.value=state[key];
  }
  function syncUi() {
    if(!drawer)return;
    ['accent','canvas','surface','text','brand'].forEach(syncColorPair);
    const values={skinRadius:state.radius,skinSurfaceOpacity:Math.round(state.surfaceOpacity*100),skinBlur:state.blur,skinFontScale:Math.round(state.fontScale*100),skinSidebarWidth:state.sidebarWidth,skinWallpaperOpacity:Math.round(state.background.opacity*100),skinWallpaperBlur:state.background.blur,skinWallpaperZoom:state.background.zoom};
    Object.entries(values).forEach(([id,value])=>{const el=document.getElementById(id);if(!el)return;el.value=String(value);const out=el.parentElement.querySelector('output');if(out){const unit=out.dataset.unit||'';out.textContent=`${value}${unit}`;}});
    drawer.querySelectorAll('#skinDensity [data-value]').forEach(b=>b.classList.toggle('is-active',b.dataset.value===state.density));
    const font=document.getElementById('skinFontFamily');if(font)font.value=state.fontFamily;
    const pos=document.getElementById('skinWallpaperPosition');if(pos)pos.value=state.background.position;
    const url=document.getElementById('skinWallpaperUrl');if(url)url.value=state.background.type==='url'?state.background.value:'';
    const name=document.getElementById('skinCustomName');if(name&&document.activeElement!==name)name.value=state.customName||'我的皮肤';
    drawer.querySelectorAll('[data-skin-preset]').forEach(card=>card.classList.toggle('is-selected',card.dataset.skinPreset===state.id));
    drawer.querySelectorAll('[data-skin-background]').forEach(card=>{const bg=BACKGROUNDS.find(x=>x.id===card.dataset.skinBackground);const selected=state.background.type==='none'?card.dataset.skinBackground==='none':state.background.type==='gradient'&&bg&&bg.value===state.background.value;card.classList.toggle('is-selected',!!selected);});
    const current=document.getElementById('skinCurrentLabel');if(current)current.textContent=`${state.customName || state.subtitle || state.name} · ${BASE_THEME_LABELS[state.base] || state.base}`;
    const ratio=contrast(state.text,state.surface);const badge=document.getElementById('skinContrastBadge');const meta=document.getElementById('skinContrastMeta');if(badge){badge.textContent=ratio>=7?'AAA':ratio>=4.5?'AA':'偏低';badge.dataset.level=ratio>=4.5?'ok':'warn';}if(meta)meta.textContent=`正文 / 面板 ${ratio.toFixed(2)}:1`;
    syncShare();
    syncSettingsSummary();
  }

  function serializePayload(includeWallpaper = false) {
    const payload=clone(state); payload.schema='galaxy-skin';payload.version=VERSION;payload.exportedAt=new Date().toISOString();
    if(!includeWallpaper && payload.background.type==='image'){payload.background={...payload.background,type:'none',value:''};payload.wallpaperOmitted=true;}
    return payload;
  }
  function encodeBase64Url(text){const bytes=new TextEncoder().encode(text);let binary='';bytes.forEach(b=>binary+=String.fromCharCode(b));return btoa(binary).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');}
  function decodeBase64Url(value){let s=value.replace(/-/g,'+').replace(/_/g,'/');while(s.length%4)s+='=';const binary=atob(s);const bytes=Uint8Array.from(binary,c=>c.charCodeAt(0));return new TextDecoder().decode(bytes);}
  function createShare(){return SHARE_PREFIX+encodeBase64Url(JSON.stringify(serializePayload(false)));}
  function parseShare(raw){if(!raw.startsWith(SHARE_PREFIX))throw new Error('不是有效的 Galaxy 皮肤分享字符串');return JSON.parse(decodeBase64Url(raw.slice(SHARE_PREFIX.length)));}
  function syncShare(){const el=document.getElementById('skinShareString');if(el)el.value=createShare();}
  async function copyShare(){const value=createShare();try{await navigator.clipboard.writeText(value);setShareStatus('分享字符串已复制。','ok');}catch{const el=document.getElementById('skinShareString');el?.select();setShareStatus('浏览器未允许剪贴板，请手动复制。','warn');}}
  function exportFile(){const payload=serializePayload(true);const blob=new Blob([JSON.stringify(payload,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=`${sanitizeFileName(state.customName||'galaxy-skin')}.galaxyskin`;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(a.href),1000);setShareStatus('皮肤文件已导出。','ok');}
  function sanitizeFileName(name){return String(name).replace(/[\\/:*?"<>|]+/g,'-').trim().slice(0,70)||'galaxy-skin';}
  function importPayload(payload,source='导入'){if(!payload||typeof payload!=='object')throw new Error('皮肤内容无效');if(payload.schema&&payload.schema!=='galaxy-skin')throw new Error('不支持的皮肤格式');previousState=clone(state);const next=normalizeState(payload);next.id='custom';next.customName=String(payload.customName||payload.subtitle||payload.name||'导入皮肤').slice(0,80);applyState(next,{announce:true});setShareStatus(`${source} 已应用。`,'ok');}
  function normalizeGithubUrl(raw){try{const u=new URL(raw);if(u.hostname==='github.com'){const m=u.pathname.match(/^\/([^/]+)\/([^/]+)\/blob\/([^/]+)\/(.+)$/);if(m)return `https://raw.githubusercontent.com/${m[1]}/${m[2]}/${m[3]}/${m[4]}`;}return u.toString();}catch{return raw;}}
  async function importFromUrl(){const input=document.getElementById('skinGithubUrl');const raw=input.value.trim();if(!/^https:\/\//i.test(raw)){setShareStatus('请输入 HTTPS 皮肤地址。','error');return;}const url=normalizeGithubUrl(raw);setShareStatus('正在获取远程皮肤…','neutral');try{const r=await fetch(url,{headers:{Accept:'application/json,text/plain;q=0.9,*/*;q=0.1'}});if(!r.ok)throw new Error(`HTTP ${r.status}`);const text=await r.text();if(text.length>6*1024*1024)throw new Error('皮肤文件过大');importPayload(JSON.parse(text),'远程皮肤');}catch(err){setShareStatus(`获取失败：${err.message}`,'error');}}
  function setShareStatus(text,tone='neutral'){const el=document.getElementById('skinShareStatus');if(el){el.textContent=text;el.dataset.tone=tone;}}

  function syncSettingsSummary() {
    const panel=document.getElementById('appearancePanel'); if(!panel)return;
    if(!panel.classList.contains('appearance-panel-v14')) panel.classList.add('appearance-panel-v14');
    const grid=panel.querySelector('.appearance-grid'); if(grid && !grid.hidden)grid.hidden=true;
    const header=panel.querySelector('.panel-header'); if(!header)return;
    const title=header.querySelector('h2'); const p=header.querySelector('p');
    if(title && title.textContent!=='皮肤与外观')title.textContent='皮肤与外观';
    const desc='完整皮肤、背景、界面密度与分享配置统一由皮肤工作室管理。';
    if(p && p.textContent!==desc)p.textContent=desc;
    let action=header.querySelector('#openSkinStudioSettings');
    if(!action){action=document.createElement('button');action.id='openSkinStudioSettings';action.className='button secondary';action.type='button';action.innerHTML=`${svgIcon('palette')}<span>打开皮肤工作室</span>`;action.addEventListener('click',openDrawer);header.querySelector('.toolbar')?.append(action);}
    const current=document.getElementById('appearanceCurrentTheme');const label=state.customName || state.subtitle || state.name;if(current && current.textContent!==label)current.textContent=label;
  }

  function bindGlobalKeys() {
    document.addEventListener('keydown',e=>{
      if((e.ctrlKey||e.metaKey)&&e.shiftKey&&e.key.toLowerCase()==='p'){e.preventDefault();openDrawer();return;}
      if(e.key==='Escape'&&drawer?.classList.contains('is-open')){e.preventDefault();closeDrawer();}
      if(e.key==='Tab'&&drawer?.classList.contains('is-open'))trapFocus(e);
    });
  }
  function trapFocus(e){const items=[...drawer.querySelectorAll('button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]')].filter(x=>x.offsetParent!==null);if(!items.length)return;const first=items[0],last=items.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}}

  function boot() {
    applyState(state,{persist:false}); injectTopButton(); injectDrawer(); bindGlobalKeys(); syncSettingsSummary();
    const observer=new MutationObserver(()=>{injectTopButton();syncSettingsSummary();}); observer.observe(document.body,{childList:true,subtree:true});
  }

  window.GalaxySkin = {
    version: VERSION,
    presets: PRESETS.map(clone),
    backgrounds: BACKGROUNDS.map(clone),
    getState: ()=>clone(state),
    apply: value=>applyState(value,{remember:true}),
    reset: ()=>applyState({...PRESETS[0],customName:PRESETS[0].subtitle},{remember:true}),
    share: createShare,
    parseShare,
    importPayload,
    normalizeGithubUrl,
    contrast,
    open: openDrawer,
    close: closeDrawer
  };

  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
;

/* ===== galaxy-v15.js ===== */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const HELPER = 'http://127.0.0.1:17837';
  let current = null;
  let selected = null;
  let filter = 'recommended';
  let inspectController = null;

  const esc = (value) => String(value ?? '').replace(/[&<>'"]/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[ch]));
  const validUrl = (value) => { try { const u = new URL(String(value || '').trim()); return ['http:','https:'].includes(u.protocol) ? u : null; } catch { return null; } };
  const isDirectImage = (url) => /\.(?:jpe?g|png|webp|avif|gif)(?:$|[?#])/i.test(url.href);
  const isDirectVideo = (url) => /\.(?:mp4|webm|mov|m4v)(?:$|[?#])/i.test(url.href);
  const isManifest = (url) => /\.(?:m3u8|mpd)(?:$|[?#])/i.test(url.href);
  const safeDecode = (value) => { try { return decodeURIComponent(String(value ?? '')); } catch { return String(value ?? ''); } };

  function setHelper(state, text) {
    const node = $('previewHelperState'); if (!node) return;
    node.dataset.state = state; node.textContent = text;
  }
  function showState(name, message = '', tone = '') {
    ['previewIdle','previewLoading','previewError','previewResult'].forEach((id) => $(id)?.classList.add('is-hidden'));
    const target = $(name); if (!target) return;
    target.classList.remove('is-hidden');
    if (name === 'previewError') { $('previewErrorCopy').innerHTML = message; target.dataset.tone = tone || 'error'; }
  }
  function formatDuration(seconds) {
    const n = Number(seconds); if (!Number.isFinite(n) || n <= 0) return '时长未知';
    const s = Math.floor(n % 60), m = Math.floor((n / 60) % 60), h = Math.floor(n / 3600);
    return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${m}:${String(s).padStart(2,'0')}`;
  }
  function formatBytes(bytes) {
    let n = Number(bytes); if (!Number.isFinite(n) || n <= 0) return '大小未知';
    const units=['B','KB','MB','GB','TB']; let i=0; while(n>=1024&&i<units.length-1){n/=1024;i++;}
    return `${n >= 100 || i === 0 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2)} ${units[i]}`;
  }
  function codecLabel(f) {
    const v = String(f.vcodec || '').split('.')[0]; const a = String(f.acodec || '').split('.')[0];
    if (f.kind === 'audio') return (a && a !== 'none' ? a : f.ext || 'audio').toUpperCase();
    if (f.kind === 'image') return `${String(f.ext||'image').toUpperCase()} · IMAGE`;
    const main = v && v !== 'none' ? v : (f.ext || 'video');
    return main.toUpperCase();
  }
  function qualityLabel(f) {
    if (f.kind === 'audio') return 'Audio';
    if (f.kind === 'image') return '原图';
    const h=Number(f.height)||0; if(h>=2160)return '4K'; if(h>=1440)return '2K'; if(h>=1080)return '1080p'; if(h>=720)return '720p'; if(h>=480)return '480p'; return h?`${h}p`:'Video';
  }
  function qualityPreset(f) {
    const h=Number(f.height)||0; if(h>=2160)return '2160'; if(h>=1440)return '1440'; if(h>=1080)return '1080'; if(h>=720)return '720'; return 'best';
  }
  function normalizeFormats(formats) {
    const list=(Array.isArray(formats)?formats:[]).map((f, i) => {
      const width=Number(f.width)||0, height=Number(f.height)||0, fps=Number(f.fps)||0;
      const vcodec=String(f.vcodec||'none'), acodec=String(f.acodec||'none');
      const kind=String(f.kind||f.media_type||'').toLowerCase()==='image'||vcodec==='image'?'image':((vcodec==='none' && acodec!=='none')?'audio':'video');
      const size=Number(f.filesize)||Number(f.filesize_approx)||0;
      const hdr=String(f.dynamic_range||f.hdr||'').toUpperCase();
      return {...f,_key:String(f.format_id||f.id||i),kind,width,height,fps,vcodec,acodec,size,hdr};
    }).filter((f)=>['audio','video','image'].includes(f.kind)&&(f.kind==='audio'||f.height||f.width));
    const seen=new Set();
    return list.sort((a,b)=>{
      if(a.kind!==b.kind){const rank={image:0,video:1,audio:2};return (rank[a.kind]??9)-(rank[b.kind]??9);}
      return (b.height-a.height)||(b.fps-a.fps)||((b.tbr||0)-(a.tbr||0));
    }).filter((f)=>{
      const key=f.kind==='audio'?`a:${f.acodec}:${Math.round(f.abr||f.tbr||0)}`:(f.kind==='image'?`i:${f.width}:${f.height}:${f.ext}`:`v:${f.height}:${Math.round(f.fps||0)}:${f.vcodec}:${f.hdr}:${f.ext}`);
      if(seen.has(key))return false; seen.add(key); return true;
    }).slice(0,36);
  }
  function recommendedFormats(list) {
    const images=list.filter(f=>f.kind==='image'); const video=list.filter(f=>f.kind==='video'); const audio=list.filter(f=>f.kind==='audio'); const picks=[];
    if(images.length){picks.push(...images.slice(0,4)); return picks;}
    for (const target of [2160,1440,1080,720]) {
      const exact=video.find(f=>f.height===target)||video.find(f=>f.height<target&&f.height>=target-240);
      if(exact&&!picks.includes(exact))picks.push(exact);
    }
    if(!picks.length&&video[0])picks.push(video[0]); if(audio[0])picks.push(audio[0]); return picks;
  }
  function filteredFormats() {
    const list=current?.formats||[];
    if(filter==='recommended') return recommendedFormats(list);
    if(filter==='image') return list.filter(f=>f.kind==='image');
    if(filter==='audio') return list.filter(f=>f.kind==='audio');
    if(filter==='4k') return list.filter(f=>f.kind==='video'&&f.height>=2160);
    if(filter==='2k') return list.filter(f=>f.kind==='video'&&f.height>=1440&&f.height<2160);
    if(filter==='1080') return list.filter(f=>f.kind==='video'&&f.height>=1080&&f.height<1440);
    return list;
  }
  function renderFormats() {
    const list=filteredFormats(); const host=$('previewFormatList'); if(!host)return;
    $('previewFormatCount').textContent=`${list.length} 个可选项`;
    document.querySelectorAll('[data-preview-filter]').forEach((b)=>b.classList.toggle('is-active',b.dataset.previewFilter===filter));
    if(!list.length){host.innerHTML='<div class="preview-format-empty">当前筛选条件下没有可用格式。</div>';return;}
    host.innerHTML=list.map((f)=>{
      const selectedClass=(selected && selected._key===f._key) ? ' is-selected' : '';
      const detail=f.kind==='audio'?`${Math.round(f.abr||f.tbr||0)||'—'} kbps`:`${f.width||'—'}×${f.height||'—'}`;
      const fps=f.kind!=='video'?'—':(f.fps?`${Math.round(f.fps)} fps`:'—');
      const hdr=f.kind==='image'?'—':(f.hdr&&f.hdr!=='SDR'?esc(f.hdr):'SDR');
      return `<button type="button" class="preview-format-row${selectedClass}" data-preview-format="${esc(f._key)}" aria-pressed="${selectedClass?'true':'false'}">
        <span class="preview-radio" aria-hidden="true"></span><span class="preview-quality"><strong>${esc(qualityLabel(f))}</strong><small>${esc(detail)}</small></span>
        <span class="preview-codec"><strong>${esc(f.kind==='image'?codecLabel(f):`${codecLabel(f)} · ${(f.ext||'').toUpperCase()}`)}</strong><small>${f.kind==='image'?'图片资源':(f.kind==='audio'?'音频流':(f.acodec&&f.acodec!=='none'?'含音频':'视频流'))}</small></span>
        <span class="preview-cell preview-fps">${esc(fps)}</span><span class="preview-cell${hdr!=='SDR'?' is-hdr':''}">${esc(hdr)}</span><span class="preview-cell preview-size">${esc(formatBytes(f.size))}</span>
      </button>`;
    }).join('');
  }
  function updateSelection() {
    const target=$('previewSelectionCopy'); if(!target)return;
    if(!selected){target.innerHTML='选择一个清晰度后，可同步到下方下载设置。'; $('previewApplyButton').disabled=true; return;}
    const desc=selected.kind==='image'?`原图 · ${selected.width||'—'}×${selected.height||'—'}`:(selected.kind==='audio'?'音频':`${qualityLabel(selected)} · ${selected.height||'—'}p${selected.fps?` · ${Math.round(selected.fps)}fps`:''}`);
    target.innerHTML=`已选择 <strong>${esc(desc)}</strong> · ${esc(codecLabel(selected))} · ${esc(formatBytes(selected.size))}`;
    $('previewApplyButton').disabled=selected.kind!=='video';
  }
  function render(data) {
    const formats=normalizeFormats(data.formats); current={...data,formats}; selected=recommendedFormats(formats).find(f=>f.kind==='video')||formats.find(f=>f.kind==='video')||formats[0]||null;
    const thumb=$('previewThumbnail'); const fallback=$('previewThumbFallback');
    if(data.thumbnail){thumb.src=data.thumbnail;thumb.hidden=false;fallback.hidden=true;thumb.onerror=()=>{thumb.hidden=true;fallback.hidden=false;};}else{thumb.hidden=true;fallback.hidden=false;}
    $('previewTitle').textContent=data.title||'未命名媒体';
    $('previewSource').textContent=data.extractor||data.source_host||'网页媒体';
    $('previewDuration').textContent=formatDuration(data.duration);
    const mediaType=String(data.media_type||'').toLowerCase(); const maxVideo=formats.find(f=>f.kind==='video'); const maxImage=formats.find(f=>f.kind==='image'); const bestH=Number(data.height)||maxVideo?.height||maxImage?.height||0; const bestW=Number(data.width)||maxImage?.width||0; const bestFps=Number(data.fps)||maxVideo?.fps||0;
    $('previewBest').textContent=mediaType==='image'||maxImage&&!maxVideo?`${bestW||'—'}×${bestH||'—'}`:(bestH?`${bestH}p${bestFps?` · ${Math.round(bestFps)}fps`:''}`:'格式已解析');
    const imageCount=formats.filter(f=>f.kind==='image').length, videoCount=formats.filter(f=>f.kind==='video').length;
    $('previewFormatSummary').textContent=imageCount||videoCount;
    $('previewFormatSummaryLabel').textContent=imageCount&&!videoCount?'个图片资源':'个视频格式';
    const imageOnly=imageCount>0&&videoCount===0;
    if($('previewMetaNote')) $('previewMetaNote').textContent=imageOnly?'已读取直接图片的真实像素尺寸；商品页包含多张图片时，建议使用“原图 / 图集”批量抓取。':'选择下方清晰度只会同步“质量档位”；最终封装与音视频合并仍由本地 yt-dlp + FFmpeg 完成。';
    if($('previewAccuracyNote')) $('previewAccuracyNote').innerHTML=imageOnly?'<strong>说明：</strong>图片资源不会映射为视频质量；直接图片可按当前链接下载，多图商品页建议使用“原图 / 图集”。':'<strong>说明：</strong>V1.5 不伪造“精确格式下载”。现有 Galaxy 协议仍按质量档位工作，因此格式预览用于决策，应用后映射到 4K / 2K / 1080p / 720p / 最高质量。';
    filter='recommended'; renderFormats(); updateSelection(); showState('previewResult');
  }
  async function helperHealth() {
    try{const r=await fetch(`${HELPER}/health`,{cache:'no-store',headers:{'X-Galaxy-Preview':'1'}}); if(r.ok){setHelper('online','解析服务在线');return true;}}catch{}
    setHelper('offline','解析服务未启动'); return false;
  }
  async function inspectDirectImage(url) {
    return new Promise((resolve,reject)=>{const img=new Image();const timer=setTimeout(()=>reject(new Error('图片元数据读取超时')),12000);img.onload=()=>{clearTimeout(timer);resolve({title:safeDecode(url.pathname.split('/').pop()||'Direct image'),extractor:'直接图片',media_type:'image',thumbnail:url.href,width:img.naturalWidth,height:img.naturalHeight,duration:0,formats:[{format_id:'image',kind:'image',ext:(url.pathname.split('.').pop()||'image').toLowerCase(),width:img.naturalWidth,height:img.naturalHeight,vcodec:'image',acodec:'none'}]});};img.onerror=()=>{clearTimeout(timer);reject(new Error('无法读取图片元数据'));};img.src=url.href;});
  }
  async function inspectDirectVideo(url) {
    return new Promise((resolve,reject)=>{const v=document.createElement('video');v.preload='metadata';const timer=setTimeout(()=>reject(new Error('视频元数据读取超时')),14000);v.onloadedmetadata=()=>{clearTimeout(timer);resolve({title:safeDecode(url.pathname.split('/').pop()||'Direct video'),extractor:'直接视频',media_type:'video',thumbnail:'',width:v.videoWidth,height:v.videoHeight,duration:v.duration,formats:[{format_id:'direct',ext:(url.pathname.split('.').pop()||'video').toLowerCase(),width:v.videoWidth,height:v.videoHeight,vcodec:'direct',acodec:'unknown'}]});v.remove();};v.onerror=()=>{clearTimeout(timer);reject(new Error('浏览器无法直接读取该视频，请使用本地解析服务'));v.remove();};v.src=url.href;});
  }
  async function inspectViaHelper(url) {
    inspectController?.abort(); inspectController=new AbortController();
    const browser=$('quickBrowser')?.value||'none';
    const timer=setTimeout(()=>inspectController.abort(),48000);
    try{
      const endpoint=`${HELPER}/inspect?url=${encodeURIComponent(url.href)}&browser=${encodeURIComponent(browser)}`;
      const response=await fetch(endpoint,{method:'GET',cache:'no-store',signal:inspectController.signal,headers:{'X-Galaxy-Preview':'1'}});
      const data=await response.json().catch(()=>({})); if(!response.ok||data.ok===false)throw new Error(data.error||`HTTP ${response.status}`); return data.media||data;
    } finally {clearTimeout(timer);}
  }
  async function inspect() {
    const url=validUrl($('quickSourceUrl')?.value); if(!url){showState('previewError','请输入有效的 http / https 链接后再解析。','error');$('quickSourceUrl')?.focus();return;}
    $('quickInspectButton').disabled=true; showState('previewLoading');
    try{
      let data;
      if(isDirectImage(url)) data=await inspectDirectImage(url);
      else if(isDirectVideo(url)) { try{data=await inspectDirectVideo(url);}catch{data=await inspectViaHelper(url);} }
      else data=await inspectViaHelper(url);
      render(data); setHelper('online','解析服务在线');
    }catch(error){
      const galleryHint=/homedepot|wayfair|lowes|walmart|amazon|pinterest|alibaba|aliexpress|made-in-china/i.test(url.hostname);
      const hint=galleryHint?' 这类商品/图集页面也可以直接使用「下载原图 / 图集」。':' 仍可直接使用下方“开始下载”，或重新从 Launch-Modern-UI.cmd 启动以加载解析服务。';
      showState('previewError',`<strong>暂时无法取得媒体清单。</strong>${esc(error?.message||'解析服务不可用')}。${hint}`,'warn'); setHelper('offline','解析服务未启动');
    }finally{$('quickInspectButton').disabled=false;}
  }
  function applySelected() {
    if(!selected||selected.kind!=='video')return;
    const select=$('quickVideoQuality'); if(!select)return;
    const preset=qualityPreset(selected); if(Array.from(select.options).some(o=>o.value===preset)) select.value=preset; else select.value='best';
    select.dispatchEvent(new Event('change',{bubbles:true}));
    const status=$('quickInlineStatus'); if(status){status.textContent=`已将 ${qualityLabel(selected)} 映射到下载质量；实际下载仍由 yt-dlp 选择最佳匹配格式。`;status.dataset.tone='success';}
  }
  function clearForUrlChange() {
    current=null;selected=null;filter='recommended'; showState('previewIdle');
  }
  function boot() {
    $('quickInspectButton')?.addEventListener('click',inspect);
    $('quickSourceUrl')?.addEventListener('input',()=>{if(current)clearForUrlChange();});
    $('previewFormatList')?.addEventListener('click',(event)=>{const row=event.target.closest('[data-preview-format]');if(!row||!current)return;selected=current.formats.find(f=>f._key===row.dataset.previewFormat)||null;renderFormats();updateSelection();});
    document.querySelectorAll('[data-preview-filter]').forEach((b)=>b.addEventListener('click',()=>{filter=b.dataset.previewFilter;renderFormats();}));
    $('previewApplyButton')?.addEventListener('click',applySelected);
    $('previewDownloadButton')?.addEventListener('click',()=>{$('quickDownloadButton')?.click();});
    $('quickSourceUrl')?.addEventListener('keydown',(event)=>{if(event.key==='Enter'&&(event.ctrlKey||event.metaKey)){event.preventDefault();inspect();}});
    helperHealth();
    window.GalaxyMediaPreview={inspect,normalizeFormats,recommendedFormats,qualityPreset,getState:()=>({current,selected,filter})};
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot,{once:true});else boot();
})();
;
