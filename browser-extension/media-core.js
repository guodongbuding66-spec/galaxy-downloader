const MEDIA_EXTENSIONS = Object.freeze({
  video: new Set(["mp4", "webm", "mov", "m4v", "mkv", "avi", "flv", "ts"]),
  audio: new Set(["mp3", "m4a", "aac", "flac", "wav", "ogg", "opus", "weba"]),
  image: new Set(["jpg", "jpeg", "png", "webp", "gif", "avif", "bmp", "svg"]),
  hls: new Set(["m3u8"]),
  dash: new Set(["mpd"]),
});

const SOURCE_WEIGHTS = Object.freeze({
  "dom-current-src": 50,
  "dom-source": 45,
  "dom-srcset": 42,
  "meta-media": 38,
  "performance": 30,
  "web-request": 28,
  "page-probe": 26,
});

const MAX_URL_LENGTH = 8192;
const MAX_LABEL_LENGTH = 240;

function cleanText(value, limit = MAX_LABEL_LENGTH) {
  return String(value ?? "")
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, limit);
}

function safeUrl(value, baseUrl) {
  const text = String(value ?? "").trim();
  if (!text || text.length > MAX_URL_LENGTH || /^(?:blob|data|javascript|chrome|chrome-extension):/i.test(text)) {
    return null;
  }
  try {
    const parsed = new URL(text, baseUrl || undefined);
    if (!/^https?:$/.test(parsed.protocol) || parsed.username || parsed.password) return null;
    parsed.hash = "";
    return parsed.href;
  } catch {
    return null;
  }
}

function extensionFromUrl(url) {
  try {
    const path = new URL(url).pathname.toLowerCase();
    const match = path.match(/\.([a-z0-9]{2,8})$/);
    return match?.[1] || "";
  } catch {
    return "";
  }
}

function mimeKind(mimeType) {
  const mime = String(mimeType || "").toLowerCase().split(";", 1)[0].trim();
  if (!mime) return "unknown";
  if (mime === "application/vnd.apple.mpegurl" || mime === "application/x-mpegurl") return "hls";
  if (mime === "application/dash+xml") return "dash";
  if (mime.startsWith("video/")) return "video";
  if (mime.startsWith("audio/")) return "audio";
  if (mime.startsWith("image/")) return "image";
  return "unknown";
}

export function classifyMediaUrl(url, mimeType = "") {
  const byMime = mimeKind(mimeType);
  if (byMime !== "unknown") return byMime;
  const ext = extensionFromUrl(url);
  for (const [kind, extensions] of Object.entries(MEDIA_EXTENSIONS)) {
    if (extensions.has(ext)) return kind;
  }
  const lower = String(url || "").toLowerCase();
  if (/[?&](?:format|type)=m3u8(?:&|$)/.test(lower)) return "hls";
  if (/[?&](?:format|type)=mpd(?:&|$)/.test(lower)) return "dash";
  return "unknown";
}

export function normalizeCandidate(raw, { baseUrl = "" } = {}) {
  if (!raw || typeof raw !== "object") return null;
  const url = safeUrl(raw.url, baseUrl || raw.pageUrl);
  if (!url) return null;
  const kind = classifyMediaUrl(url, raw.mimeType);
  if (kind === "unknown" && raw.mediaKind !== "unknown") {
    if (!["video", "audio", "image", "hls", "dash"].includes(raw.mediaKind)) return null;
  }
  const resolvedKind = kind === "unknown" ? raw.mediaKind || "unknown" : kind;
  if (resolvedKind === "unknown") return null;

  const width = Number(raw.width);
  const height = Number(raw.height);
  return {
    url,
    mediaKind: resolvedKind,
    mimeType: cleanText(raw.mimeType, 120),
    source: SOURCE_WEIGHTS[raw.source] ? raw.source : "page-probe",
    label: cleanText(raw.label),
    width: Number.isFinite(width) && width > 0 ? Math.round(width) : null,
    height: Number.isFinite(height) && height > 0 ? Math.round(height) : null,
    pageUrl: safeUrl(raw.pageUrl || baseUrl) || "",
  };
}

export function candidateKey(candidate) {
  return `${candidate.mediaKind}:${candidate.url}`;
}

function sourceQualitySignal(url) {
  const lower = String(url || "").toLowerCase();
  let score = 0;
  if (/(?:original|origin|source|download|master|raw|no[_-]?watermark|watermark[_-]?free)/.test(lower)) score += 20;
  if (/(?:thumbnail|thumb|preview|poster|sprite)/.test(lower)) score -= 18;
  if (/(?:watermarked|watermark|logo[_-]?overlay)/.test(lower)) score -= 14;
  return score;
}

export function scoreCandidate(candidate) {
  let score = SOURCE_WEIGHTS[candidate?.source] || 0;
  const kind = candidate?.mediaKind;
  if (kind === "video") score += 40;
  else if (kind === "audio") score += 34;
  else if (kind === "hls" || kind === "dash") score += 32;
  else if (kind === "image") score += 24;
  score += sourceQualitySignal(candidate?.url);
  if (candidate?.width && candidate?.height) {
    const pixels = candidate.width * candidate.height;
    score += Math.min(24, Math.log2(Math.max(1, pixels / 65536)) * 3);
  }
  return score;
}

export function candidateQualityLabel(candidate) {
  const width = Number(candidate?.width) || 0;
  const height = Number(candidate?.height) || 0;
  if (candidate?.mediaKind === "hls" || candidate?.mediaKind === "dash") return "自适应流";
  if (!width || !height) return "质量未知";
  if (candidate?.mediaKind === "image") {
    const megapixels = (width * height) / 1_000_000;
    return megapixels >= 1 ? `${megapixels.toFixed(megapixels >= 10 ? 0 : 1)} MP · ${width}×${height}` : `${width}×${height}`;
  }
  if (height >= 2160) return `4K · ${width}×${height}`;
  if (height >= 1440) return `1440p · ${width}×${height}`;
  if (height >= 1080) return `1080p · ${width}×${height}`;
  if (height >= 720) return `720p · ${width}×${height}`;
  return `${width}×${height}`;
}

export function mergeCandidates(existing, incoming, { limit = 200 } = {}) {
  const map = new Map();
  for (const candidate of [...(existing || []), ...(incoming || [])]) {
    if (!candidate?.url || !candidate?.mediaKind) continue;
    const key = candidateKey(candidate);
    const current = map.get(key);
    if (!current || scoreCandidate(candidate) > scoreCandidate(current)) map.set(key, candidate);
  }
  return [...map.values()]
    .sort((a, b) => scoreCandidate(b) - scoreCandidate(a) || a.url.localeCompare(b.url))
    .slice(0, Math.max(1, Math.min(500, Number(limit) || 200)));
}

export function canDirectDownload(candidate) {
  return ["video", "audio", "image"].includes(candidate?.mediaKind);
}

export function requiresGalaxyHandoff(candidate) {
  return ["hls", "dash"].includes(candidate?.mediaKind);
}

export function suggestedFilename(candidate) {
  try {
    const parsed = new URL(candidate.url);
    let name = decodeURIComponent(parsed.pathname.split("/").pop() || "").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
    if (!name || name.length > 160) name = `galaxy-${candidate.mediaKind}`;
    if (!name.includes(".")) {
      const ext = candidate.mediaKind === "video" ? "mp4" : candidate.mediaKind === "audio" ? "m4a" : candidate.mediaKind === "image" ? "jpg" : "bin";
      name += `.${ext}`;
    }
    return name.slice(0, 180);
  } catch {
    return `galaxy-${candidate?.mediaKind || "media"}`;
  }
}

export function publicCandidate(candidate, id) {
  return {
    id,
    mediaKind: candidate.mediaKind,
    source: candidate.source,
    label: candidate.label,
    width: candidate.width,
    height: candidate.height,
    qualityLabel: candidateQualityLabel(candidate),
    rankScore: Math.round(scoreCandidate(candidate)),
    directDownload: canDirectDownload(candidate),
    galaxyHandoff: requiresGalaxyHandoff(candidate),
  };
}
