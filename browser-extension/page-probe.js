(() => {
  "use strict";

  const MESSAGE_SOURCE = "galaxy-media-capture-main";
  const seen = new Set();

  function emit(url, source = "performance") {
    const value = String(url || "").trim();
    if (!/^https?:\/\//i.test(value) || seen.has(value)) return;
    seen.add(value);
    window.postMessage(
      {
        source: MESSAGE_SOURCE,
        type: "galaxy:resource-candidate",
        candidate: {
          url: value,
          pageUrl: location.href,
          source,
          mediaKind: "unknown",
        },
      },
      "*",
    );
  }

  function scanExistingResources() {
    try {
      for (const entry of performance.getEntriesByType("resource")) emit(entry.name, "performance");
    } catch {
      // Resource Timing can be restricted by a page; webRequest remains the
      // browser-level fallback and the isolated content script still scans DOM.
    }
  }

  scanExistingResources();

  if (typeof PerformanceObserver === "function") {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) emit(entry.name, "performance");
      });
      observer.observe({ type: "resource", buffered: true });
    } catch {
      // Older Chromium builds may reject the buffered resource form.
      try {
        const observer = new PerformanceObserver((list) => {
          for (const entry of list.getEntries()) emit(entry.name, "performance");
        });
        observer.observe({ entryTypes: ["resource"] });
      } catch {
        // DOM + webRequest collection continue to operate.
      }
    }
  }
})();
