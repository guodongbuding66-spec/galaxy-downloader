interface DurableObjectStorageLike {
  get<T>(key: string): Promise<T | undefined>;
  put<T>(key: string, value: T): Promise<void>;
}

interface DurableObjectStateLike {
  storage: DurableObjectStorageLike;
}

interface DurableObjectStubLike {
  fetch(input: RequestInfo | URL, init?: RequestInit): Promise<Response>;
}

export interface DurableObjectNamespaceLike {
  idFromName(name: string): unknown;
  get(id: unknown): DurableObjectStubLike;
}

type ProxyRateLimitBucket = "image-preview" | "image-download" | "media-download";

interface ProxyRateLimitConfig {
  limit: number;
  windowSeconds: number;
}

interface ProxyRateLimitState {
  windowStartMs: number;
  count: number;
}

export const PROXY_RATE_LIMITS: Record<ProxyRateLimitBucket, ProxyRateLimitConfig> = {
  // A large article can legitimately contain 100+ images. Keep preview and
  // archive/download traffic in separate buckets so normal article workflows
  // do not rate-limit themselves while still bounding public relay abuse.
  "image-preview": { limit: 240, windowSeconds: 60 },
  "image-download": { limit: 180, windowSeconds: 60 },
  "media-download": { limit: 60, windowSeconds: 60 },
};

function bucketForRequest(url: URL): ProxyRateLimitBucket | null {
  if (url.pathname === "/api/proxy-image") {
    return url.searchParams.get("mode") === "download" ? "image-download" : "image-preview";
  }
  if (url.pathname === "/api/proxy-media") {
    return "media-download";
  }
  return null;
}

function fixedWindowStart(nowMs: number, windowMs: number): number {
  return Math.floor(nowMs / windowMs) * windowMs;
}

function rateHeaders(config: ProxyRateLimitConfig, remaining: number, resetSeconds: number): Headers {
  const headers = new Headers({
    "cache-control": "private, no-store",
    "ratelimit-limit": String(config.limit),
    "ratelimit-remaining": String(Math.max(0, remaining)),
    "ratelimit-reset": String(Math.max(1, resetSeconds)),
    "x-ratelimit-limit": String(config.limit),
    "x-ratelimit-remaining": String(Math.max(0, remaining)),
    "x-ratelimit-reset": String(Math.max(1, resetSeconds)),
  });
  return headers;
}

/**
 * One Durable Object instance is addressed per Cloudflare client IP. The
 * object keeps independent fixed-window counters for image preview, image
 * archive/download and media download traffic.
 */
export class ProxyRateLimiter {
  private readonly state: DurableObjectStateLike;

  constructor(state: DurableObjectStateLike) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    const bucket = url.searchParams.get("bucket") as ProxyRateLimitBucket | null;
    if (!bucket || !(bucket in PROXY_RATE_LIMITS)) {
      return Response.json({ allowed: false, error: "Unknown rate-limit bucket" }, { status: 400 });
    }

    const config = PROXY_RATE_LIMITS[bucket];
    const windowMs = config.windowSeconds * 1000;
    const nowMs = Date.now();
    const windowStartMs = fixedWindowStart(nowMs, windowMs);
    const resetSeconds = Math.ceil((windowStartMs + windowMs - nowMs) / 1000);
    const key = `bucket:${bucket}`;
    const previous = await this.state.storage.get<ProxyRateLimitState>(key);
    const current: ProxyRateLimitState = previous?.windowStartMs === windowStartMs
      ? previous
      : { windowStartMs, count: 0 };

    if (current.count >= config.limit) {
      const headers = rateHeaders(config, 0, resetSeconds);
      headers.set("retry-after", String(Math.max(1, resetSeconds)));
      return Response.json({ allowed: false, error: "Proxy rate limit exceeded" }, { status: 429, headers });
    }

    current.count += 1;
    await this.state.storage.put(key, current);
    return Response.json(
      { allowed: true },
      { headers: rateHeaders(config, config.limit - current.count, resetSeconds) },
    );
  }
}

/**
 * Cloudflare provides CF-Connecting-IP on production Worker requests. Local
 * dev/test requests may omit it; in that case this defense-in-depth limiter is
 * skipped instead of collapsing every local request into one shared bucket.
 */
export async function enforceProxyRateLimit(
  request: Request,
  namespace: DurableObjectNamespaceLike,
): Promise<Response | null> {
  const url = new URL(request.url);
  const bucket = bucketForRequest(url);
  if (!bucket) return null;

  const clientIp = request.headers.get("cf-connecting-ip")?.trim();
  if (!clientIp) return null;

  try {
    const id = namespace.idFromName(`proxy-client:${clientIp}`);
    const internalUrl = new URL("https://proxy-rate-limit.invalid/check");
    internalUrl.searchParams.set("bucket", bucket);
    const decision = await namespace.get(id).fetch(new Request(internalUrl, { method: "POST" }));
    if (decision.status !== 429) return null;

    const headers = new Headers(decision.headers);
    headers.set("content-type", "application/json; charset=utf-8");
    headers.set("x-robots-tag", "noindex, nofollow, noarchive");
    return new Response(JSON.stringify({ error: "Too many proxy requests. Please retry shortly." }), {
      status: 429,
      headers,
    });
  } catch (error) {
    // Do not turn an optional abuse-control dependency into an availability
    // outage. Cloudflare WAF/rate-limit rules can remain an additional layer.
    console.error("Proxy rate limiter failed open", {
      error: error instanceof Error ? error.message : String(error),
    });
    return null;
  }
}
