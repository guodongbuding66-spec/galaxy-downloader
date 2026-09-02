(() => {
  "use strict";

  const MAIN_SOURCE = "galaxy-media-capture-main";
  const UI_HOST_ID = "galaxy-media-capture-host";
  const MAX_BATCH = 120;
  const seenDom = new Set();
  let blobObserved = false;
  let currentPageUrl = location.href;
  let scanTimer = 0;
  let host = null;
  let shadow = null;
  let chip = null;
  let panel = null;
  let statusNode = null;

  function absoluteUrl(value) {
    const text = String(value || "").trim();
    if (!text) return "";
    if (/^blob:/i.test(text)) {
      blobObserved = true;
      return "";
    }
    if (/^(?:data|javascript|chrome|chrome-extension):/i.test(text)) return "";
    try {
      const parsed = new URL(text, location.href);
      return /^https?:$/.test(parsed.protocol) ? parsed.href : "";
    } catch {
      return "";
    }
  }

  function addCandidate(target, candidate) {
    const url = absoluteUrl(candidate.url);
    if (!url) return;
    const key = `${candidate.mediaKind || "unknown"}:${url}`;
    if (seenDom.has(key)) return;
    seenDom.add(key);
    target.push({
      ...candidate,
      url,
      pageUrl: location.href,
      label: String(candidate.label || "").slice(0, 240),
    });
  }

  function srcsetUrls(value) {
    return String(value || "")
      .split(",")
      .map((part) => part.trim().split(/\s+/, 1)[0])
      .filter(Boolean);
  }

  function scanDom(root = document) {
    const candidates = [];
    const scope = root?.querySelectorAll ? root : document;

    for (const media of scope.querySelectorAll("video, audio")) {
      const mediaKind = media.tagName.toLowerCase() === "audio" ? "audio" : "video";
      const src = media.currentSrc || media.src;
      if (/^blob:/i.test(String(src || ""))) blobObserved = true;
      addCandidate(candidates, {
        url: src,
        mediaKind,
        source: "dom-current-src",
        label: media.getAttribute("aria-label") || media.getAttribute("title") || `${mediaKind} source`,
        width: mediaKind === "video" ? media.videoWidth : null,
        height: mediaKind === "video" ? media.videoHeight : null,
      });
      for (const source of media.querySelectorAll("source[src]")) {
        addCandidate(candidates, {
          url: source.src,
          mediaKind,
          mimeType: source.type,
          source: "dom-source",
          label: source.getAttribute("data-quality") || source.getAttribute("label") || `${mediaKind} source`,
        });
      }
    }

    for (const image of scope.querySelectorAll("img")) {
      addCandidate(candidates, {
        url: image.currentSrc || image.src,
        mediaKind: "image",
        source: "dom-current-src",
        label: image.alt || image.title || "image",
        width: image.naturalWidth,
        height: image.naturalHeight,
      });
      for (const url of srcsetUrls(image.srcset)) {
        addCandidate(candidates, {
          url,
          mediaKind: "image",
          source: "dom-srcset",
          label: image.alt || "responsive image",
        });
      }
    }

    for (const source of scope.querySelectorAll("picture source[srcset]")) {
      for (const url of srcsetUrls(source.srcset)) {
        addCandidate(candidates, {
          url,
          mediaKind: "image",
          mimeType: source.type,
          source: "dom-srcset",
          label: "picture source",
        });
      }
    }

    const metaSelectors = [
      ["meta[property='og:video'][content]", "video"],
      ["meta[property='og:video:url'][content]", "video"],
      ["meta[property='og:audio'][content]", "audio"],
      ["meta[property='og:image'][content]", "image"],
      ["meta[name='twitter:image'][content]", "image"],
      ["meta[name='twitter:player:stream'][content]", "video"],
    ];
    for (const [selector, mediaKind] of metaSelectors) {
      for (const meta of scope.querySelectorAll(selector)) {
        addCandidate(candidates, {
          url: meta.content,
          mediaKind,
          source: "meta-media",
          label: meta.getAttribute("property") || meta.getAttribute("name") || "page media",
        });
      }
    }

    for (const link of scope.querySelectorAll("link[rel='image_src'][href], link[rel='preload'][as='image'][href]")) {
      addCandidate(candidates, {
        url: link.href,
        mediaKind: "image",
        source: "meta-media",
        label: "page image",
      });
    }

    if (candidates.length) sendCandidates(candidates.slice(0, MAX_BATCH));
    refreshChip();
  }

  function walkJsonLd(value, candidates, depth = 0) {
    if (depth > 6 || candidates.length >= 60 || value == null) return;
    if (Array.isArray(value)) {
      for (const item of value) walkJsonLd(item, candidates, depth + 1);
      return;
    }
    if (typeof value !== "object") return;
    const type = String(value["@type"] || "").toLowerCase();
    const mediaKind = type.includes("audio") ? "audio" : type.includes("image") ? "image" : "video";
    for (const key of ["contentUrl", "embedUrl"] ) {
      if (typeof value[key] === "string") {
        addCandidate(candidates, {
          url: value[key],
          mediaKind,
          source: "meta-media",
          label: value.name || value.headline || `JSON-LD ${key}`,
        });
      }
    }
    const thumbnails = value.thumbnailUrl;
    for (const thumbnail of Array.isArray(thumbnails) ? thumbnails : thumbnails ? [thumbnails] : []) {
      if (typeof thumbnail === "string") {
        addCandidate(candidates, {
          url: thumbnail,
          mediaKind: "image",
          source: "meta-media",
          label: "JSON-LD thumbnail",
        });
      }
    }
    for (const child of Object.values(value)) walkJsonLd(child, candidates, depth + 1);
  }

  function scanJsonLd() {
    const candidates = [];
    for (const script of document.querySelectorAll("script[type='application/ld+json']")) {
      try {
        walkJsonLd(JSON.parse(script.textContent || "null"), candidates);
      } catch {
        // Invalid page metadata is ignored.
      }
    }
    if (candidates.length) sendCandidates(candidates.slice(0, MAX_BATCH));
  }

  function sendCandidates(candidates) {
    chrome.runtime.sendMessage({
      type: "galaxy:candidate-batch",
      pageUrl: location.href,
      candidates,
    }).then((response) => {
      if (response?.ok) updateChipCount(response.count || 0);
    }).catch(() => {});
  }

  function scheduleScan(root = document) {
    window.clearTimeout(scanTimer);
    scanTimer = window.setTimeout(() => {
      scanDom(root);
      scanJsonLd();
    }, 120);
  }

  function resetForPage() {
    currentPageUrl = location.href;
    seenDom.clear();
    blobObserved = false;
    chrome.runtime.sendMessage({ type: "galaxy:page-reset", pageUrl: currentPageUrl }).catch(() => {});
    scheduleScan(document);
  }

  function candidateTitle(candidate) {
    const type = {
      video: "视频",
      audio: "音频",
      image: "图片",
      hls: "HLS",
      dash: "DASH",
    }[candidate.mediaKind] || "媒体";
    const size = candidate.width && candidate.height ? ` · ${candidate.width}×${candidate.height}` : "";
    return `${type}${size}`;
  }

  function openGalaxy(targetUrl) {
    const target = String(targetUrl || location.href);
    const protocol = `galaxy-downloader://download?url=${encodeURIComponent(target)}&include_audio=1`;
    const anchor = document.createElement("a");
    anchor.href = protocol;
    anchor.style.display = "none";
    document.documentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setStatus("已请求 Galaxy Local Engine 处理；浏览器可能会询问是否打开桌面应用。", "info");
  }

  async function handoffCandidate(candidate) {
    if (["hls", "dash"].includes(candidate.mediaKind)) {
      try {
        const response = await chrome.runtime.sendMessage({ type: "galaxy:get-handoff-source", id: candidate.id });
        if (response?.ok && response.url) {
          openGalaxy(response.url);
          return;
        }
      } catch {
        // Fall through to page-level yt-dlp extraction.
      }
    }
    openGalaxy(location.href);
  }

  async function downloadCandidate(candidate) {
    setStatus("正在交给 Chrome 下载…", "info");
    try {
      const response = await chrome.runtime.sendMessage({ type: "galaxy:download-candidate", id: candidate.id });
      if (response?.ok) setStatus("已创建浏览器下载任务。", "success");
      else setStatus(response?.error || "浏览器无法直接下载这个媒体源。", "error");
    } catch (error) {
      setStatus(String(error?.message || error), "error");
    }
  }

  function setStatus(text, kind = "info") {
    if (!statusNode) return;
    statusNode.textContent = text;
    statusNode.dataset.kind = kind;
  }

  function updateChipCount(count) {
    if (!chip) return;
    const total = Number(count) || 0;
    chip.textContent = total > 0 ? `Galaxy · ${total}` : blobObserved ? "Galaxy · Blob" : "Galaxy";
    chip.style.opacity = total > 0 || blobObserved ? "1" : "0.58";
  }

  async function refreshChip() {
    try {
      const response = await chrome.runtime.sendMessage({ type: "galaxy:get-candidates" });
      if (response?.ok) updateChipCount(response.count || 0);
    } catch {
      // Extension may be reloading.
    }
  }

  async function renderPanel() {
    if (!panel) return;
    panel.replaceChildren();
    const header = document.createElement("div");
    header.className = "g-header";
    header.innerHTML = `<strong>Galaxy 媒体发现</strong><button class="g-close" type="button">×</button>`;
    header.querySelector("button")?.addEventListener("click", () => panel.classList.remove("open"));
    panel.appendChild(header);

    const hint = document.createElement("div");
    hint.className = "g-hint";
    hint.textContent = "仅列出页面实际暴露的媒体源；不会绕过 DRM/EME。";
    panel.appendChild(hint);

    let response;
    try {
      response = await chrome.runtime.sendMessage({ type: "galaxy:get-candidates" });
    } catch {
      response = null;
    }
    const candidates = response?.ok && Array.isArray(response.candidates) ? response.candidates : [];

    const list = document.createElement("div");
    list.className = "g-list";
    for (const candidate of candidates.slice(0, 30)) {
      const row = document.createElement("div");
      row.className = "g-row";
      const text = document.createElement("div");
      text.className = "g-row-text";
      const title = document.createElement("strong");
      title.textContent = candidateTitle(candidate);
      const sub = document.createElement("span");
      sub.textContent = candidate.label || candidate.source || "已发现媒体源";
      text.append(title, sub);
      const actions = document.createElement("div");
      actions.className = "g-actions";
      if (candidate.directDownload) {
        const direct = document.createElement("button");
        direct.type = "button";
        direct.textContent = "直接下载";
        direct.addEventListener("click", () => void downloadCandidate(candidate));
        actions.appendChild(direct);
      }
      const galaxy = document.createElement("button");
      galaxy.type = "button";
      galaxy.className = "primary";
      galaxy.textContent = "Galaxy";
      galaxy.addEventListener("click", () => void handoffCandidate(candidate));
      actions.appendChild(galaxy);
      row.append(text, actions);
      list.appendChild(row);
    }

    if (!candidates.length && !blobObserved) {
      const empty = document.createElement("div");
      empty.className = "g-empty";
      empty.textContent = "当前还没有发现可下载媒体。播放视频或滚动页面后会继续观察。";
      list.appendChild(empty);
    }
    if (blobObserved) {
      const row = document.createElement("div");
      row.className = "g-row blob";
      const text = document.createElement("div");
      text.className = "g-row-text";
      text.innerHTML = "<strong>Blob / MSE</strong><span>Blob URL 不是可移植源；优先使用已观察到的上游媒体。若没有上游源，可让 Galaxy 重新解析页面。</span>";
      const actions = document.createElement("div");
      actions.className = "g-actions";
      const galaxy = document.createElement("button");
      galaxy.type = "button";
      galaxy.className = "primary";
      galaxy.textContent = "解析页面";
      galaxy.addEventListener("click", () => openGalaxy(location.href));
      actions.appendChild(galaxy);
      row.append(text, actions);
      list.appendChild(row);
    }
    panel.appendChild(list);

    statusNode = document.createElement("div");
    statusNode.className = "g-status";
    statusNode.textContent = `${candidates.length} 个候选源 · 数据仅保存在扩展内存中`;
    panel.appendChild(statusNode);
  }

  function installUi() {
    if (document.getElementById(UI_HOST_ID)) return;
    host = document.createElement("div");
    host.id = UI_HOST_ID;
    host.style.cssText = "all:initial;position:fixed;right:18px;bottom:18px;z-index:2147483647;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host{all:initial}
      *{box-sizing:border-box}
      .g-chip{pointer-events:auto;border:1px solid rgba(255,255,255,.16);background:#0f172a;color:#f8fafc;border-radius:999px;padding:9px 12px;font:600 12px/1 system-ui,-apple-system,"Segoe UI",sans-serif;box-shadow:0 10px 30px rgba(0,0,0,.28);cursor:pointer;transition:.15s ease}
      .g-chip:hover{transform:translateY(-1px);background:#172033}
      .g-panel{display:none;pointer-events:auto;position:absolute;right:0;bottom:44px;width:min(420px,calc(100vw - 36px));max-height:min(560px,70vh);overflow:hidden;background:#0b1220;color:#e5edf7;border:1px solid #263348;border-radius:14px;box-shadow:0 18px 60px rgba(0,0,0,.42);font:12px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
      .g-panel.open{display:block}
      .g-header{display:flex;align-items:center;justify-content:space-between;padding:12px 13px;border-bottom:1px solid #202c3d}.g-header strong{font-size:13px}.g-close{border:0;background:transparent;color:#94a3b8;font-size:20px;line-height:1;cursor:pointer}
      .g-hint{padding:9px 13px;color:#94a3b8;background:#0e1728;border-bottom:1px solid #202c3d}
      .g-list{max-height:400px;overflow:auto;padding:6px}
      .g-row{display:flex;gap:10px;align-items:center;padding:9px;border-radius:10px}.g-row:hover{background:#121d30}.g-row.blob{border-top:1px dashed #2b3b52;margin-top:5px;padding-top:12px}
      .g-row-text{min-width:0;flex:1;display:flex;flex-direction:column}.g-row-text strong{color:#f8fafc;font-size:12px}.g-row-text span{color:#8fa1b7;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:230px}
      .g-actions{display:flex;gap:5px}.g-actions button{border:1px solid #34445c;background:#172238;color:#dce8f6;border-radius:7px;padding:5px 7px;font:600 11px/1 system-ui;cursor:pointer}.g-actions button.primary{background:#0ea5e9;border-color:#0ea5e9;color:white}
      .g-empty{padding:18px 12px;color:#8fa1b7;text-align:center}.g-status{padding:8px 12px;border-top:1px solid #202c3d;color:#7dd3fc}.g-status[data-kind="success"]{color:#86efac}.g-status[data-kind="error"]{color:#fca5a5}
    `;
    chip = document.createElement("button");
    chip.className = "g-chip";
    chip.type = "button";
    chip.textContent = "Galaxy";
    panel = document.createElement("div");
    panel.className = "g-panel";
    chip.addEventListener("click", async () => {
      const opening = !panel.classList.contains("open");
      panel.classList.toggle("open", opening);
      if (opening) await renderPanel();
    });
    shadow.append(style, panel, chip);
    document.documentElement.appendChild(host);
    void refreshChip();
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.source !== MAIN_SOURCE || event.data?.type !== "galaxy:resource-candidate") return;
    const candidate = event.data.candidate;
    if (!candidate || typeof candidate !== "object") return;
    sendCandidates([{ ...candidate, source: "performance", pageUrl: location.href }]);
  });

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      for (const node of mutation.addedNodes) {
        if (node.nodeType === Node.ELEMENT_NODE) {
          scheduleScan(node);
          return;
        }
      }
      if (mutation.type === "attributes") {
        scheduleScan(mutation.target);
        return;
      }
    }
  });

  installUi();
  resetForPage();
  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src", "srcset", "poster"],
  });

  window.setInterval(() => {
    if (location.href !== currentPageUrl) resetForPage();
  }, 1000);
})();
