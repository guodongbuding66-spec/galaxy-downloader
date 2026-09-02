import {
  canDirectDownload,
  mergeCandidates,
  normalizeCandidate,
  publicCandidate,
  requiresGalaxyHandoff,
  suggestedFilename,
} from "./media-core.js";

const MAX_CANDIDATES_PER_TAB = 200;
const tabs = new Map();

function stateFor(tabId) {
  let state = tabs.get(tabId);
  if (!state) {
    state = { pageUrl: "", candidates: [], nextId: 1, byId: new Map() };
    tabs.set(tabId, state);
  }
  return state;
}

async function updateBadge(tabId, count) {
  try {
    await chrome.action.setBadgeBackgroundColor({ tabId, color: "#0ea5e9" });
    await chrome.action.setBadgeText({ tabId, text: count > 0 ? String(Math.min(count, 99)) : "" });
  } catch {
    // Tabs can disappear between a network event and the async badge update.
  }
}

function rebuildIds(state) {
  const previousByKey = new Map();
  for (const [id, candidate] of state.byId.entries()) {
    previousByKey.set(`${candidate.mediaKind}:${candidate.url}`, id);
  }
  const next = new Map();
  for (const candidate of state.candidates) {
    const key = `${candidate.mediaKind}:${candidate.url}`;
    const id = previousByKey.get(key) || String(state.nextId++);
    next.set(id, candidate);
  }
  state.byId = next;
}

function addCandidates(tabId, rawCandidates, pageUrl = "") {
  if (!Number.isInteger(tabId) || tabId < 0) return 0;
  const state = stateFor(tabId);
  if (pageUrl && state.pageUrl && pageUrl !== state.pageUrl) {
    state.candidates = [];
    state.byId.clear();
    state.nextId = 1;
  }
  if (pageUrl) state.pageUrl = pageUrl;

  const normalized = [];
  for (const raw of Array.isArray(rawCandidates) ? rawCandidates : []) {
    const candidate = normalizeCandidate(raw, { baseUrl: pageUrl || state.pageUrl });
    if (candidate) normalized.push(candidate);
  }
  if (!normalized.length) return state.candidates.length;
  state.candidates = mergeCandidates(state.candidates, normalized, { limit: MAX_CANDIDATES_PER_TAB });
  rebuildIds(state);
  void updateBadge(tabId, state.candidates.length);
  return state.candidates.length;
}

function snapshot(tabId) {
  const state = stateFor(tabId);
  const candidateToId = new Map([...state.byId.entries()].map(([id, candidate]) => [candidate, id]));
  return {
    count: state.candidates.length,
    candidates: state.candidates.map((candidate) => publicCandidate(candidate, candidateToId.get(candidate) || "")),
  };
}

function responseHeader(headers, name) {
  const target = String(name).toLowerCase();
  const item = (headers || []).find((header) => String(header.name || "").toLowerCase() === target);
  return String(item?.value || "");
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  const tabId = sender.tab?.id;
  if (!Number.isInteger(tabId)) {
    sendResponse({ ok: false, error: "A tab context is required." });
    return false;
  }

  if (message?.type === "galaxy:page-reset") {
    const state = stateFor(tabId);
    state.pageUrl = String(message.pageUrl || "");
    state.candidates = [];
    state.byId.clear();
    state.nextId = 1;
    void updateBadge(tabId, 0);
    sendResponse({ ok: true, count: 0 });
    return false;
  }

  if (message?.type === "galaxy:candidate-batch") {
    const count = addCandidates(tabId, message.candidates, String(message.pageUrl || sender.tab?.url || ""));
    sendResponse({ ok: true, count });
    return false;
  }

  if (message?.type === "galaxy:get-candidates") {
    sendResponse({ ok: true, ...snapshot(tabId) });
    return false;
  }

  if (message?.type === "galaxy:download-candidate") {
    const candidate = stateFor(tabId).byId.get(String(message.id || ""));
    if (!candidate || !canDirectDownload(candidate)) {
      sendResponse({ ok: false, error: "This source must be handled by Galaxy Local Engine." });
      return false;
    }
    chrome.downloads
      .download({
        url: candidate.url,
        filename: suggestedFilename(candidate),
        saveAs: Boolean(message.saveAs),
      })
      .then((downloadId) => sendResponse({ ok: true, downloadId }))
      .catch((error) => sendResponse({ ok: false, error: String(error?.message || error) }));
    return true;
  }

  if (message?.type === "galaxy:get-handoff-source") {
    const candidate = stateFor(tabId).byId.get(String(message.id || ""));
    if (!candidate) {
      sendResponse({ ok: false, error: "Media source not found." });
      return false;
    }
    // Returning the real URL is allowed only in direct response to a user action.
    // It is never persisted to chrome.storage or exposed in passive UI snapshots.
    sendResponse({
      ok: true,
      url: candidate.url,
      mediaKind: candidate.mediaKind,
      usePageUrl: !requiresGalaxyHandoff(candidate) && !canDirectDownload(candidate),
    });
    return false;
  }

  sendResponse({ ok: false, error: "Unknown Galaxy extension message." });
  return false;
});

chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    if (!Number.isInteger(details.tabId) || details.tabId < 0) return;
    const mimeType = responseHeader(details.responseHeaders, "content-type");
    const raw = {
      url: details.url,
      pageUrl: stateFor(details.tabId).pageUrl,
      mimeType,
      mediaKind: "unknown",
      source: "web-request",
      label: "Network media",
    };
    addCandidates(details.tabId, [raw]);
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"],
);

chrome.tabs.onRemoved.addListener((tabId) => {
  tabs.delete(tabId);
});
