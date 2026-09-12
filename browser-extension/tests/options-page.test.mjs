import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
const html = fs.readFileSync(path.join(root, "options.html"), "utf8");
const script = fs.readFileSync(path.join(root, "options.js"), "utf8");
const css = fs.readFileSync(path.join(root, "options.css"), "utf8");

test("manifest exposes the shared settings page", () => {
  assert.deepEqual(manifest.options_ui, { page: "options.html", open_in_tab: true });
});

test("settings page exposes every persisted discovery control", () => {
  for (const id of [
    "ignored-domains",
    "min-image-width",
    "min-image-height",
    "min-video-width",
    "min-video-height",
    "auto-handoff",
    "save",
    "reset",
    "status",
  ]) assert(html.includes(`id="${id}"`), id);
  assert(html.includes('type="module" src="options.js"'));
});

test("settings page uses the existing bounded message contract", () => {
  assert(script.includes('type: "galaxy:get-settings"'));
  assert(script.includes('type: "galaxy:save-settings"'));
  assert(script.includes("defaultExtensionSettings"));
  assert(script.includes("event.ctrlKey || event.metaKey"));
  assert(!script.includes("chrome.storage"));
});

test("settings UI includes responsive and dark-mode treatment", () => {
  assert(css.includes("@media(max-width:700px)"));
  assert(css.includes("@media(prefers-color-scheme:dark)"));
  assert(css.includes("focus-visible"));
});
