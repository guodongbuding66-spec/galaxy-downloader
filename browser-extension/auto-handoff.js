(() => {
  "use strict";

  const STREAM_KINDS = new Set(["hls", "dash"]);

  function openGalaxy(targetUrl) {
    const target = String(targetUrl || "").trim();
    if (!target) return false;
    const anchor = document.createElement("a");
    anchor.href = `galaxy-downloader://download?url=${encodeURIComponent(target)}&include_audio=1&preview=1`;
    anchor.style.display = "none";
    document.documentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    return true;
  }

  async function handleAutoHandoff(id) {
    const candidateId = String(id || "").trim();
    if (!candidateId) return false;
    const response = await chrome.runtime.sendMessage({ type: "galaxy:get-handoff-source", id: candidateId });
    if (!response?.ok || !STREAM_KINDS.has(response.mediaKind) || !response.url) return false;
    return openGalaxy(response.url);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type !== "galaxy:auto-handoff") return false;
    handleAutoHandoff(message.id)
      .then((opened) => sendResponse({ ok: Boolean(opened) }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  });
})();
