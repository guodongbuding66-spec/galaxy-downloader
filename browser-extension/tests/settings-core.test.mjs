import assert from "node:assert/strict";
import test from "node:test";

import {
  EXTENSION_SETTINGS_LIMITS,
  candidatePassesMinimumSize,
  defaultExtensionSettings,
  domainIsIgnored,
  filterCandidatesForSettings,
  normalizeExtensionSettings,
} from "../settings-core.js";

test("defaults match the roadmap discovery thresholds and stay opt-in", () => {
  assert.deepEqual(defaultExtensionSettings(), {
    ignoredDomains: [],
    minImageWidth: 60,
    minImageHeight: 60,
    minVideoWidth: 120,
    minVideoHeight: 80,
    autoHandoff: false,
  });
});

test("settings normalization is bounded and rejects malformed ignored domains", () => {
  const normalized = normalizeExtensionSettings({
    ignoredDomains: [
      " Example.COM ",
      ".sub.example.com.",
      "example.com",
      "https://bad.example/path",
      "localhost",
      "-bad.example",
      "good-domain.test",
    ],
    minImageWidth: -1,
    minImageHeight: 9000,
    minVideoWidth: "640",
    minVideoHeight: 0,
    autoHandoff: "yes",
  });
  assert.deepEqual(normalized.ignoredDomains, ["example.com", "sub.example.com", "good-domain.test"]);
  assert.equal(normalized.minImageWidth, 1);
  assert.equal(normalized.minImageHeight, 4096);
  assert.equal(normalized.minVideoWidth, 640);
  assert.equal(normalized.minVideoHeight, 1);
  assert.equal(normalized.autoHandoff, false);
});

test("ignored domain applies to the exact host and subdomains only", () => {
  const settings = normalizeExtensionSettings({ ignoredDomains: ["example.com"] });
  assert.equal(domainIsIgnored("https://example.com/watch", settings), true);
  assert.equal(domainIsIgnored("https://media.example.com/file", settings), true);
  assert.equal(domainIsIgnored("https://notexample.com/file", settings), false);
  assert.equal(domainIsIgnored("not a url", settings), false);
});

test("minimum sizes remove known tiny image/video noise but retain unknown dimensions and audio/streams", () => {
  const settings = defaultExtensionSettings();
  assert.equal(candidatePassesMinimumSize({ mediaKind: "image", width: 59, height: 60 }, settings), false);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "image", width: 60, height: 60 }, settings), true);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "video", width: 119, height: 80 }, settings), false);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "video", width: 120, height: 80 }, settings), true);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "video", width: null, height: null }, settings), true);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "audio", width: 1, height: 1 }, settings), true);
  assert.equal(candidatePassesMinimumSize({ mediaKind: "hls" }, settings), true);
});

test("domain ignore wins before candidate size filtering", () => {
  const candidates = [
    { mediaKind: "image", width: 800, height: 600 },
    { mediaKind: "video", width: 1920, height: 1080 },
  ];
  const settings = normalizeExtensionSettings({ ignoredDomains: ["blocked.example"] });
  assert.deepEqual(filterCandidatesForSettings(candidates, "https://blocked.example/post", settings), []);
  assert.equal(filterCandidatesForSettings(candidates, "https://allowed.example/post", settings).length, 2);
});

test("ignored-domain list is bounded", () => {
  const domains = Array.from({ length: 150 }, (_, index) => `host-${index}.example`);
  const normalized = normalizeExtensionSettings({ ignoredDomains: domains });
  assert.equal(normalized.ignoredDomains.length, EXTENSION_SETTINGS_LIMITS.maxIgnoredDomains);
});
