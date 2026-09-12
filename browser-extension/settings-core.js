const MAX_IGNORED_DOMAINS = 100;
const MAX_DOMAIN_LENGTH = 253;
const DEFAULTS = Object.freeze({
  ignoredDomains: Object.freeze([]),
  minImageWidth: 60,
  minImageHeight: 60,
  minVideoWidth: 120,
  minVideoHeight: 80,
  autoHandoff: false,
});

function boundedInteger(value, fallback, low, high) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.max(low, Math.min(high, Math.round(parsed)));
}

function normalizeDomain(value) {
  const raw = String(value ?? "").trim().toLowerCase().replace(/^\.+|\.+$/g, "");
  if (!raw || raw.length > MAX_DOMAIN_LENGTH || raw.includes("/") || raw.includes(":") || raw.includes("@")) return "";
  if (raw === "localhost" || raw.endsWith(".localhost")) return "";
  const labels = raw.split(".");
  if (labels.some((label) => !label || label.length > 63 || !/^[a-z0-9-]+$/.test(label) || label.startsWith("-") || label.endsWith("-"))) {
    return "";
  }
  return raw;
}

function normalizeIgnoredDomains(value) {
  const seen = new Set();
  const result = [];
  for (const item of Array.isArray(value) ? value : []) {
    const domain = normalizeDomain(item);
    if (!domain || seen.has(domain)) continue;
    seen.add(domain);
    result.push(domain);
    if (result.length >= MAX_IGNORED_DOMAINS) break;
  }
  return result;
}

export function normalizeExtensionSettings(raw = {}) {
  const source = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  return {
    ignoredDomains: normalizeIgnoredDomains(source.ignoredDomains),
    minImageWidth: boundedInteger(source.minImageWidth, DEFAULTS.minImageWidth, 1, 4096),
    minImageHeight: boundedInteger(source.minImageHeight, DEFAULTS.minImageHeight, 1, 4096),
    minVideoWidth: boundedInteger(source.minVideoWidth, DEFAULTS.minVideoWidth, 1, 8192),
    minVideoHeight: boundedInteger(source.minVideoHeight, DEFAULTS.minVideoHeight, 1, 8192),
    autoHandoff: source.autoHandoff === true,
  };
}

export function defaultExtensionSettings() {
  return normalizeExtensionSettings(DEFAULTS);
}

export function domainIsIgnored(pageUrl, settings) {
  let hostname = "";
  try {
    hostname = new URL(String(pageUrl || "")).hostname.toLowerCase().replace(/\.$/, "");
  } catch {
    return false;
  }
  if (!hostname) return false;
  const normalized = normalizeExtensionSettings(settings);
  return normalized.ignoredDomains.some((domain) => hostname === domain || hostname.endsWith(`.${domain}`));
}

export function candidatePassesMinimumSize(candidate, settings) {
  const normalized = normalizeExtensionSettings(settings);
  const kind = candidate?.mediaKind;
  const width = Number(candidate?.width);
  const height = Number(candidate?.height);
  // Network/meta candidates frequently do not expose dimensions. Do not discard
  // them here: the threshold applies only when the browser supplied dimensions.
  if (!Number.isFinite(width) || !Number.isFinite(height) || width <= 0 || height <= 0) return true;
  if (kind === "image") return width >= normalized.minImageWidth && height >= normalized.minImageHeight;
  if (kind === "video") return width >= normalized.minVideoWidth && height >= normalized.minVideoHeight;
  return true;
}

export function filterCandidatesForSettings(candidates, pageUrl, settings) {
  if (domainIsIgnored(pageUrl, settings)) return [];
  return (Array.isArray(candidates) ? candidates : []).filter((candidate) => candidatePassesMinimumSize(candidate, settings));
}

export const EXTENSION_SETTINGS_LIMITS = Object.freeze({
  maxIgnoredDomains: MAX_IGNORED_DOMAINS,
  maxDomainLength: MAX_DOMAIN_LENGTH,
});
