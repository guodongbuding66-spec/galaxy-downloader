import { defaultExtensionSettings } from "./settings-core.js";

const fields = {
  ignoredDomains: document.querySelector("#ignored-domains"),
  minImageWidth: document.querySelector("#min-image-width"),
  minImageHeight: document.querySelector("#min-image-height"),
  minVideoWidth: document.querySelector("#min-video-width"),
  minVideoHeight: document.querySelector("#min-video-height"),
  autoHandoff: document.querySelector("#auto-handoff"),
};
const saveButton = document.querySelector("#save");
const resetButton = document.querySelector("#reset");
const statusNode = document.querySelector("#status");
const domainCountNode = document.querySelector("#domain-count");

function setStatus(text, kind = "info") {
  statusNode.textContent = String(text || "");
  statusNode.dataset.kind = kind;
}

function normalizedDomainLines() {
  return String(fields.ignoredDomains.value || "")
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function updateDomainCount() {
  domainCountNode.textContent = `${Math.min(normalizedDomainLines().length, 100)} / 100`;
}

function renderSettings(settings) {
  const value = settings || defaultExtensionSettings();
  fields.ignoredDomains.value = Array.isArray(value.ignoredDomains) ? value.ignoredDomains.join("\n") : "";
  fields.minImageWidth.value = Number(value.minImageWidth) || 60;
  fields.minImageHeight.value = Number(value.minImageHeight) || 60;
  fields.minVideoWidth.value = Number(value.minVideoWidth) || 120;
  fields.minVideoHeight.value = Number(value.minVideoHeight) || 80;
  fields.autoHandoff.checked = value.autoHandoff === true;
  updateDomainCount();
}

function collectSettings() {
  return {
    ignoredDomains: normalizedDomainLines(),
    minImageWidth: Number(fields.minImageWidth.value),
    minImageHeight: Number(fields.minImageHeight.value),
    minVideoWidth: Number(fields.minVideoWidth.value),
    minVideoHeight: Number(fields.minVideoHeight.value),
    autoHandoff: fields.autoHandoff.checked,
  };
}

async function loadSettings() {
  saveButton.disabled = true;
  resetButton.disabled = true;
  try {
    const response = await chrome.runtime.sendMessage({ type: "galaxy:get-settings" });
    if (!response?.ok || !response.settings) throw new Error("无法读取扩展设置。");
    renderSettings(response.settings);
    setStatus("设置已加载。", "success");
  } catch (error) {
    renderSettings(defaultExtensionSettings());
    setStatus(String(error?.message || error || "无法读取扩展设置。"), "error");
  } finally {
    saveButton.disabled = false;
    resetButton.disabled = false;
  }
}

async function saveSettings(settings = collectSettings(), successText = "设置已保存。") {
  saveButton.disabled = true;
  resetButton.disabled = true;
  setStatus("正在保存…");
  try {
    const response = await chrome.runtime.sendMessage({ type: "galaxy:save-settings", settings });
    if (!response?.ok || !response.settings) throw new Error(response?.error || "无法保存扩展设置。");
    renderSettings(response.settings);
    setStatus(successText, "success");
  } catch (error) {
    setStatus(String(error?.message || error || "无法保存扩展设置。"), "error");
  } finally {
    saveButton.disabled = false;
    resetButton.disabled = false;
  }
}

fields.ignoredDomains.addEventListener("input", updateDomainCount);
saveButton.addEventListener("click", () => void saveSettings());
resetButton.addEventListener("click", () => void saveSettings(defaultExtensionSettings(), "已恢复默认设置。"));

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    void saveSettings();
  }
});

void loadSettings();
