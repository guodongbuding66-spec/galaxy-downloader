const STREAM_KINDS = new Set(["hls", "dash"]);

export function autoHandoffKey(candidate) {
  if (!candidate || !STREAM_KINDS.has(candidate.mediaKind)) return "";
  const url = String(candidate.url || "").trim();
  return url ? `${candidate.mediaKind}:${url}` : "";
}

export function pendingAutoHandoffs(byId, settings, completed = new Set(), pending = new Set()) {
  if (!settings?.autoHandoff || !(byId instanceof Map)) return [];
  const result = [];
  for (const [id, candidate] of byId.entries()) {
    const key = autoHandoffKey(candidate);
    if (!key || completed.has(key) || pending.has(key)) continue;
    result.push({ id: String(id), key });
  }
  return result;
}
