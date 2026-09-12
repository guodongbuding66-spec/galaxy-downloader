import assert from "node:assert/strict";
import test from "node:test";

import { autoHandoffKey, pendingAutoHandoffs } from "../handoff-policy.js";

const hls = { mediaKind: "hls", url: "https://cdn.example/master.m3u8" };
const dash = { mediaKind: "dash", url: "https://cdn.example/manifest.mpd" };
const mp4 = { mediaKind: "video", url: "https://cdn.example/video.mp4" };

test("auto handoff is opt-in and limited to stream candidates", () => {
  const byId = new Map([["1", hls], ["2", dash], ["3", mp4]]);
  assert.deepEqual(pendingAutoHandoffs(byId, { autoHandoff: false }), []);
  assert.deepEqual(
    pendingAutoHandoffs(byId, { autoHandoff: true }).map((row) => row.id),
    ["1", "2"],
  );
});

test("completed and in-flight stream keys are not handed off twice", () => {
  const byId = new Map([["1", hls], ["2", dash]]);
  const completed = new Set([autoHandoffKey(hls)]);
  const pending = new Set([autoHandoffKey(dash)]);
  assert.deepEqual(pendingAutoHandoffs(byId, { autoHandoff: true }, completed, pending), []);
});

test("candidate key never exists for direct-download media", () => {
  assert.equal(autoHandoffKey(mp4), "");
  assert.equal(autoHandoffKey({ mediaKind: "image", url: "https://cdn.example/image.jpg" }), "");
  assert.equal(autoHandoffKey({ mediaKind: "hls", url: "" }), "");
});
