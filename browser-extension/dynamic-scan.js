(() => {
  "use strict";

  const MAX_BATCH = 80;
  let timer = 0;
  const pendingRoots = new Set();

  function absoluteUrl(value) {
    const text = String(value || "").trim();
    if (!text || /^(?:blob|data|javascript|chrome|chrome-extension):/i.test(text)) return "";
    try {
      const parsed = new URL(text, location.href);
      return /^https?:$/.test(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : "";
    } catch {
      return "";
    }
  }

  function collectElement(element, out) {
    if (!(element instanceof Element) || out.length >= MAX_BATCH) return;

    const add = (raw) => {
      const url = absoluteUrl(raw.url);
      if (!url || out.length >= MAX_BATCH) return;
      out.push({ ...raw, url, pageUrl: location.href });
    };

    const visit = (node) => {
      const tag = node.tagName?.toLowerCase();
      if (tag === "video" || tag === "audio") {
        const mediaKind = tag === "audio" ? "audio" : "video";
        add({
          url: node.currentSrc || node.src,
          mediaKind,
          source: "dom-current-src",
          label: node.getAttribute("aria-label") || node.getAttribute("title") || `${mediaKind} source`,
          width: mediaKind === "video" ? node.videoWidth : null,
          height: mediaKind === "video" ? node.videoHeight : null,
        });
        for (const source of node.querySelectorAll("source[src]")) {
          add({
            url: source.src,
            mediaKind,
            mimeType: source.type,
            source: "dom-source",
            label: source.getAttribute("data-quality") || source.getAttribute("label") || `${mediaKind} source`,
          });
        }
      } else if (tag === "img") {
        add({
          url: node.currentSrc || node.src,
          mediaKind: "image",
          source: "dom-current-src",
          label: node.alt || node.title || "image",
          width: node.naturalWidth,
          height: node.naturalHeight,
        });
      } else if (tag === "source" && node.src) {
        const parentTag = node.parentElement?.tagName?.toLowerCase();
        if (parentTag === "video" || parentTag === "audio") {
          add({
            url: node.src,
            mediaKind: parentTag === "audio" ? "audio" : "video",
            mimeType: node.type,
            source: "dom-source",
            label: node.getAttribute("data-quality") || node.getAttribute("label") || "media source",
          });
        }
      }
    };

    visit(element);
    for (const node of element.querySelectorAll("video,audio,img,source[src]")) {
      visit(node);
      if (out.length >= MAX_BATCH) break;
    }
  }

  function flush() {
    timer = 0;
    const candidates = [];
    for (const root of pendingRoots) {
      collectElement(root, candidates);
      if (candidates.length >= MAX_BATCH) break;
    }
    pendingRoots.clear();
    if (!candidates.length) return;
    chrome.runtime.sendMessage({
      type: "galaxy:candidate-batch",
      pageUrl: location.href,
      candidates,
    }).catch(() => {});
  }

  function schedule(root) {
    if (root instanceof Element) pendingRoots.add(root);
    clearTimeout(timer);
    timer = setTimeout(flush, 100);
  }

  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === "attributes") schedule(mutation.target);
      for (const node of mutation.addedNodes) schedule(node);
    }
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["src", "srcset", "poster"],
  });
})();
