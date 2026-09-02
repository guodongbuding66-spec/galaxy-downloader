(() => {
  "use strict";

  const HOST_ID = "galaxy-media-element-actions-host";
  const MIN_IMAGE_WIDTH = 120;
  const MIN_IMAGE_HEIGHT = 80;
  const HIDE_DELAY_MS = 160;

  let activeElement = null;
  let activeCandidate = null;
  let hideTimer = 0;
  let host = null;
  let tray = null;
  let directButton = null;
  let galaxyButton = null;
  let status = null;

  function mediaKindFor(element) {
    const tag = element?.tagName?.toLowerCase();
    if (tag === "video") return "video";
    if (tag === "audio") return "audio";
    if (tag === "img") return "image";
    return "";
  }

  function publicHttpUrl(value) {
    const text = String(value || "").trim();
    if (!text || /^(?:blob|data|javascript|chrome|chrome-extension):/i.test(text)) return "";
    try {
      const parsed = new URL(text, location.href);
      if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) return "";
      parsed.hash = "";
      return parsed.href;
    } catch {
      return "";
    }
  }

  function candidateFor(element) {
    const mediaKind = mediaKindFor(element);
    if (!mediaKind) return null;

    if (mediaKind === "image") {
      const rect = element.getBoundingClientRect();
      if (rect.width < MIN_IMAGE_WIDTH || rect.height < MIN_IMAGE_HEIGHT) return null;
    }

    const rawSource = element.currentSrc || element.src || "";
    const url = publicHttpUrl(rawSource);
    const isBlob = /^blob:/i.test(String(rawSource || ""));
    if (!url && !isBlob) return null;

    return {
      url,
      isBlob,
      mediaKind,
      source: "dom-current-src",
      label:
        element.getAttribute("aria-label") ||
        element.getAttribute("alt") ||
        element.getAttribute("title") ||
        `${mediaKind} source`,
      width:
        mediaKind === "video"
          ? Number(element.videoWidth) || null
          : mediaKind === "image"
            ? Number(element.naturalWidth) || null
            : null,
      height:
        mediaKind === "video"
          ? Number(element.videoHeight) || null
          : mediaKind === "image"
            ? Number(element.naturalHeight) || null
            : null,
      pageUrl: location.href,
    };
  }

  function openGalaxy(url) {
    const target = publicHttpUrl(url) || location.href;
    const protocol = `galaxy-downloader://download?url=${encodeURIComponent(target)}&include_audio=1`;
    const anchor = document.createElement("a");
    anchor.href = protocol;
    anchor.style.display = "none";
    document.documentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setStatus("已交给 Galaxy", "success");
  }

  function setStatus(text, kind = "info") {
    if (!status) return;
    status.textContent = text;
    status.dataset.kind = kind;
  }

  function positionTray() {
    if (!activeElement || !tray || !document.contains(activeElement)) {
      hideNow();
      return;
    }
    const rect = activeElement.getBoundingClientRect();
    if (rect.bottom < 0 || rect.top > innerHeight || rect.right < 0 || rect.left > innerWidth) {
      hideNow();
      return;
    }

    const trayWidth = Math.max(150, tray.getBoundingClientRect().width || 150);
    const left = Math.max(8, Math.min(innerWidth - trayWidth - 8, rect.right - trayWidth - 8));
    const top = Math.max(8, Math.min(innerHeight - 38, rect.top + 8));
    tray.style.transform = `translate3d(${Math.round(left)}px, ${Math.round(top)}px, 0)`;
  }

  function showFor(element) {
    const candidate = candidateFor(element);
    if (!candidate) return;
    clearTimeout(hideTimer);
    activeElement = element;
    activeCandidate = candidate;
    tray.hidden = false;
    directButton.hidden = Boolean(candidate.isBlob || !candidate.url);
    galaxyButton.textContent = candidate.isBlob ? "Galaxy 解析" : "Galaxy";
    status.textContent = "";
    positionTray();
  }

  function hideNow() {
    activeElement = null;
    activeCandidate = null;
    if (tray) tray.hidden = true;
  }

  function scheduleHide() {
    clearTimeout(hideTimer);
    hideTimer = setTimeout(hideNow, HIDE_DELAY_MS);
  }

  async function directDownload() {
    const candidate = activeCandidate;
    if (!candidate?.url || candidate.isBlob) return;
    directButton.disabled = true;
    setStatus("创建下载…");
    try {
      const response = await chrome.runtime.sendMessage({
        type: "galaxy:download-observed",
        pageUrl: location.href,
        candidate,
      });
      if (response?.ok) setStatus("已开始", "success");
      else setStatus(response?.error || "下载失败", "error");
    } catch (error) {
      setStatus(String(error?.message || error || "下载失败"), "error");
    } finally {
      directButton.disabled = false;
    }
  }

  function installUi() {
    if (document.getElementById(HOST_ID)) return;
    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:fixed;inset:0;z-index:2147483646;pointer-events:none;";
    const shadow = host.attachShadow({ mode: "closed" });
    const style = document.createElement("style");
    style.textContent = `
      :host{all:initial}
      *{box-sizing:border-box}
      .tray{position:absolute;left:0;top:0;display:flex;align-items:center;gap:5px;pointer-events:auto;padding:4px;background:rgba(9,16,29,.92);border:1px solid rgba(255,255,255,.16);border-radius:9px;box-shadow:0 8px 24px rgba(0,0,0,.32);backdrop-filter:blur(8px);font:600 11px/1 system-ui,-apple-system,"Segoe UI",sans-serif;white-space:nowrap}
      .tray[hidden]{display:none}
      button{appearance:none;border:1px solid #33445e;border-radius:6px;background:#162238;color:#e7eff8;padding:6px 8px;font:inherit;cursor:pointer}
      button:hover{background:#21314d}button.primary{background:#0ea5e9;border-color:#0ea5e9;color:white}button.primary:hover{background:#0284c7}button:disabled{opacity:.55;cursor:wait}
      .status{max-width:90px;overflow:hidden;text-overflow:ellipsis;color:#8fa1b7}.status[data-kind="success"]{color:#86efac}.status[data-kind="error"]{color:#fca5a5}
    `;
    tray = document.createElement("div");
    tray.className = "tray";
    tray.hidden = true;
    directButton = document.createElement("button");
    directButton.type = "button";
    directButton.textContent = "↓ 下载";
    directButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      void directDownload();
    });
    galaxyButton = document.createElement("button");
    galaxyButton.type = "button";
    galaxyButton.className = "primary";
    galaxyButton.textContent = "Galaxy";
    galaxyButton.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      const candidate = activeCandidate;
      if (!candidate) return;
      openGalaxy(candidate.isBlob ? location.href : candidate.url);
    });
    status = document.createElement("span");
    status.className = "status";
    tray.addEventListener("pointerenter", () => clearTimeout(hideTimer));
    tray.addEventListener("pointerleave", scheduleHide);
    tray.append(directButton, galaxyButton, status);
    shadow.append(style, tray);
    document.documentElement.appendChild(host);
  }

  document.addEventListener(
    "pointerover",
    (event) => {
      const target = event.target;
      if (!(target instanceof Element)) return;
      const media = target.closest("video,audio,img");
      if (media) showFor(media);
    },
    true,
  );

  document.addEventListener(
    "pointerout",
    (event) => {
      if (!activeElement) return;
      const related = event.relatedTarget;
      if (related instanceof Node && activeElement.contains(related)) return;
      scheduleHide();
    },
    true,
  );

  window.addEventListener("scroll", positionTray, true);
  window.addEventListener("resize", positionTray);
  installUi();
})();
