import assert from "node:assert/strict";
import test from "node:test";

import {
  canDirectDownload,
  classifyMediaUrl,
  mergeCandidates,
  normalizeCandidate,
  publicCandidate,
  requiresGalaxyHandoff,
  scoreCandidate,
  suggestedFilename,
} from "../media-core.js";

test("classifies direct media and manifests by MIME or extension", () => {
  assert.equal(classifyMediaUrl("https://cdn.example/video.mp4"), "video");
  assert.equal(classifyMediaUrl("https://cdn.example/audio?id=1", "audio/ogg; codecs=opus"), "audio");
  assert.equal(classifyMediaUrl("https://cdn.example/master.m3u8"), "hls");
  assert.equal(classifyMediaUrl("https://cdn.example/manifest", "application/dash+xml"), "dash");
  assert.equal(classifyMediaUrl("https://cdn.example/photo.avif"), "image");
});

test("normalization rejects blob data credentials and unknown noise", () => {
  assert.equal(normalizeCandidate({ url: "blob:https://example.test/id", mediaKind: "video" }), null);
  assert.equal(normalizeCandidate({ url: "data:image/png;base64,AA==", mediaKind: "image" }), null);
  assert.equal(normalizeCandidate({ url: "https://user:pass@example.test/video.mp4" }), null);
  assert.equal(normalizeCandidate({ url: "https://example.test/api/ping", mediaKind: "unknown" }), null);
});

test("extensionless CDN sources can use a DOM media hint", () => {
  const candidate = normalizeCandidate({
    url: "/cdn/playback?id=42",
    pageUrl: "https://example.test/watch",
    mediaKind: "video",
    source: "dom-current-src",
    width: 1920,
    height: 1080,
  });
  assert.ok(candidate);
  assert.equal(candidate.mediaKind, "video");
  assert.equal(candidate.url, "https://example.test/cdn/playback?id=42");
  assert.equal(candidate.width, 1920);
});

test("candidate ranking prefers exposed original sources without mutating URLs", () => {
  const original = normalizeCandidate({
    url: "https://cdn.example/original/video.mp4?token=abc",
    mediaKind: "video",
    source: "dom-current-src",
  });
  const watermarked = normalizeCandidate({
    url: "https://cdn.example/watermarked/video.mp4?token=abc",
    mediaKind: "video",
    source: "dom-current-src",
  });
  assert.ok(original && watermarked);
  assert.ok(scoreCandidate(original) > scoreCandidate(watermarked));
  assert.equal(original.url, "https://cdn.example/original/video.mp4?token=abc");
});

test("merge deduplicates exact candidates and keeps the strongest observation", () => {
  const weak = normalizeCandidate({
    url: "https://cdn.example/video.mp4",
    mediaKind: "video",
    source: "web-request",
  });
  const strong = normalizeCandidate({
    url: "https://cdn.example/video.mp4",
    mediaKind: "video",
    source: "dom-current-src",
    width: 1920,
    height: 1080,
  });
  assert.ok(weak && strong);
  const merged = mergeCandidates([weak], [strong]);
  assert.equal(merged.length, 1);
  assert.equal(merged[0].source, "dom-current-src");
  assert.equal(merged[0].width, 1920);
});

test("public passive snapshot never exposes the signed URL", () => {
  const candidate = normalizeCandidate({
    url: "https://cdn.example/video.mp4?token=secret",
    mediaKind: "video",
    source: "dom-current-src",
    label: "main video",
  });
  assert.ok(candidate);
  const payload = publicCandidate(candidate, "7");
  assert.equal(payload.id, "7");
  assert.equal(payload.directDownload, true);
  assert.equal("url" in payload, false);
  assert.equal(JSON.stringify(payload).includes("secret"), false);
});

test("only progressive media is direct-downloadable; manifests hand off to Galaxy", () => {
  assert.equal(canDirectDownload({ mediaKind: "video" }), true);
  assert.equal(canDirectDownload({ mediaKind: "image" }), true);
  assert.equal(canDirectDownload({ mediaKind: "hls" }), false);
  assert.equal(requiresGalaxyHandoff({ mediaKind: "hls" }), true);
  assert.equal(requiresGalaxyHandoff({ mediaKind: "dash" }), true);
  assert.equal(requiresGalaxyHandoff({ mediaKind: "video" }), false);
});

test("suggested filenames are bounded and filesystem-safe", () => {
  assert.equal(
    suggestedFilename({ url: "https://cdn.example/path/My%20Video.mp4?x=1", mediaKind: "video" }),
    "My Video.mp4",
  );
  assert.match(suggestedFilename({ url: "https://cdn.example/play?id=1", mediaKind: "audio" }), /\.m4a$/);
});

test("candidate list is bounded", () => {
  const items = Array.from({ length: 250 }, (_, index) =>
    normalizeCandidate({
      url: `https://cdn.example/${index}.jpg`,
      mediaKind: "image",
      source: "web-request",
    }),
  ).filter(Boolean);
  assert.equal(mergeCandidates([], items, { limit: 40 }).length, 40);
});
