const PROTOCOL_VERSION = 1;
const WEB_SOURCE = 'galaxy-web';
const COMPANION_SOURCE = 'galaxy-companion';
const ALLOWED_METHODS = new Set([
  'engine.status',
  'media.parse',
  'media.download',
  'media.cancel',
]);

function isRequest(value) {
  return Boolean(
    value
    && typeof value === 'object'
    && value.source === WEB_SOURCE
    && value.protocolVersion === PROTOCOL_VERSION
    && value.type === 'request'
    && typeof value.requestId === 'string'
    && typeof value.method === 'string'
    && ALLOWED_METHODS.has(value.method)
  );
}

window.addEventListener('message', async (event) => {
  if (event.source !== window || event.origin !== window.location.origin) return;
  if (!isRequest(event.data)) return;

  const request = event.data;
  let reply;

  try {
    const result = await chrome.runtime.sendMessage({
      type: 'GALAXY_LOCAL_ENGINE_REQUEST',
      protocolVersion: PROTOCOL_VERSION,
      requestId: request.requestId,
      method: request.method,
      params: request.params || {},
      pageUrl: window.location.href,
    });

    reply = {
      source: COMPANION_SOURCE,
      protocolVersion: PROTOCOL_VERSION,
      requestId: request.requestId,
      type: 'response',
      ok: result?.ok !== false,
      result: result?.result,
      error: result?.error,
    };
  } catch (error) {
    reply = {
      source: COMPANION_SOURCE,
      protocolVersion: PROTOCOL_VERSION,
      requestId: request.requestId,
      type: 'response',
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    };
  }

  window.postMessage(reply, window.location.origin);
});
