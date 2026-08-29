const PROTOCOL_VERSION = 1;
const ENGINE_VERSION = '0.1.0';

function engineStatus() {
  return {
    protocolVersion: PROTOCOL_VERSION,
    engineVersion: ENGINE_VERSION,
    pyodide: false,
    ytDlp: false,
    ffmpegWasm: false,
    cookies: true,
    crossOriginFetch: true,
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (
    !message
    || message.type !== 'GALAXY_LOCAL_ENGINE_REQUEST'
    || message.protocolVersion !== PROTOCOL_VERSION
    || typeof message.method !== 'string'
  ) {
    return false;
  }

  if (message.method === 'engine.status') {
    sendResponse({
      ok: true,
      result: engineStatus(),
    });
    return false;
  }

  // The protocol is intentionally wired before the Pyodide engine is bundled.
  // This keeps the web app integration stable while the local yt-dlp worker is
  // developed independently from the UI.
  sendResponse({
    ok: false,
    error: 'Local yt-dlp engine is not loaded yet',
  });
  return false;
});
