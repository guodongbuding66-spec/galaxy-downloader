(() => {
  "use strict";

  const HOST_ID = "galaxy-candidate-browser-host";
  const FILTERS = [
    ["all", "全部"],
    ["video", "视频"],
    ["audio", "音频"],
    ["image", "图片"],
    ["stream", "流媒体"],
  ];
  const SOURCE_LABELS = {
    "dom-current-src": "页面当前源",
    "dom-source": "页面 Source",
    "dom-srcset": "响应式图片",
    "meta-media": "页面元数据",
    performance: "页面资源",
    "web-request": "网络响应",
    "page-probe": "页面探针",
  };

  let host = null;
  let shadow = null;
  let dialog = null;
  let listNode = null;
  let tabsNode = null;
  let summaryNode = null;
  let statusNode = null;
  let batchButton = null;
  let selectButton = null;
  let candidates = [];
  let activeFilter = "all";
  const selectedIds = new Set();

  function matchesFilter(candidate) {
    if (activeFilter === "all") return true;
    if (activeFilter === "stream") return candidate.mediaKind === "hls" || candidate.mediaKind === "dash";
    return candidate.mediaKind === activeFilter;
  }

  function visibleCandidates() {
    return candidates.filter(matchesFilter);
  }

  function directVisibleCandidates() {
    return visibleCandidates().filter((candidate) => candidate.directDownload);
  }

  function mediaLabel(kind) {
    return {
      video: "视频",
      audio: "音频",
      image: "图片",
      hls: "HLS",
      dash: "DASH",
    }[kind] || "媒体";
  }

  function sourceLabel(source) {
    return SOURCE_LABELS[source] || "已发现媒体源";
  }

  function setStatus(text, kind = "info") {
    if (!statusNode) return;
    statusNode.textContent = String(text || "").slice(0, 220);
    statusNode.dataset.kind = kind;
  }

  function openGalaxy(targetUrl) {
    const target = String(targetUrl || location.href);
    const anchor = document.createElement("a");
    anchor.href = `galaxy-downloader://download?url=${encodeURIComponent(target)}&include_audio=1`;
    anchor.style.display = "none";
    document.documentElement.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setStatus("已请求 Galaxy Local Engine 处理。", "success");
  }

  async function handoffCandidate(candidate) {
    if (candidate.mediaKind === "hls" || candidate.mediaKind === "dash") {
      try {
        const response = await chrome.runtime.sendMessage({ type: "galaxy:get-handoff-source", id: candidate.id });
        if (response?.ok && response.url) {
          openGalaxy(response.url);
          return;
        }
      } catch {
        // Page-level parser fallback below.
      }
    }
    openGalaxy(location.href);
  }

  async function downloadOne(candidate) {
    setStatus(`正在创建 ${mediaLabel(candidate.mediaKind)} 下载任务…`);
    try {
      const response = await chrome.runtime.sendMessage({ type: "galaxy:download-candidate", id: candidate.id });
      if (response?.ok) setStatus("已创建 Chrome 下载任务。", "success");
      else setStatus(response?.error || "无法直接下载该媒体源。", "error");
    } catch (error) {
      setStatus(String(error?.message || error), "error");
    }
  }

  async function batchDownload() {
    const ids = [...selectedIds].slice(0, 20);
    if (!ids.length) {
      setStatus("请先勾选要批量下载的项目。", "error");
      return;
    }
    batchButton.disabled = true;
    setStatus(`正在提交 ${ids.length} 个下载任务…`);
    try {
      const response = await chrome.runtime.sendMessage({ type: "galaxy:download-candidates", ids });
      if (!response?.ok) {
        setStatus(response?.error || "批量下载失败。", "error");
        return;
      }
      const rejected = Array.isArray(response.rejected) ? response.rejected.length : 0;
      setStatus(`已启动 ${response.started || 0} 项${response.failed ? ` · 失败 ${response.failed}` : ""}${rejected ? ` · 拒绝 ${rejected}` : ""}。`, response.failed || rejected ? "warn" : "success");
      for (const id of ids) selectedIds.delete(id);
      renderRows();
    } catch (error) {
      setStatus(String(error?.message || error), "error");
    } finally {
      batchButton.disabled = false;
      updateSelectionUi();
    }
  }

  function countForFilter(filter) {
    if (filter === "all") return candidates.length;
    if (filter === "stream") return candidates.filter((candidate) => candidate.mediaKind === "hls" || candidate.mediaKind === "dash").length;
    return candidates.filter((candidate) => candidate.mediaKind === filter).length;
  }

  function renderTabs() {
    tabsNode.replaceChildren();
    for (const [key, label] of FILTERS) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = key === activeFilter ? "active" : "";
      button.textContent = `${label} ${countForFilter(key)}`;
      button.addEventListener("click", () => {
        activeFilter = key;
        renderTabs();
        renderRows();
      });
      tabsNode.appendChild(button);
    }
  }

  function updateSelectionUi() {
    const visibleDirect = directVisibleCandidates();
    const selectedVisible = visibleDirect.filter((candidate) => selectedIds.has(candidate.id));
    batchButton.textContent = selectedIds.size ? `批量下载 ${Math.min(selectedIds.size, 20)}` : "批量下载";
    batchButton.disabled = selectedIds.size === 0;
    selectButton.textContent = visibleDirect.length && selectedVisible.length === visibleDirect.length ? "取消全选" : "全选当前";
    selectButton.disabled = visibleDirect.length === 0;
    summaryNode.textContent = `${visibleCandidates().length} 个当前候选 · ${candidates.length} 个总候选 · 单次最多批量下载 20 项`;
  }

  function toggleSelectVisible() {
    const visibleDirect = directVisibleCandidates();
    const allSelected = visibleDirect.length > 0 && visibleDirect.every((candidate) => selectedIds.has(candidate.id));
    for (const candidate of visibleDirect) {
      if (allSelected) selectedIds.delete(candidate.id);
      else selectedIds.add(candidate.id);
    }
    renderRows();
  }

  function renderRows() {
    listNode.replaceChildren();
    const visible = visibleCandidates();
    if (!visible.length) {
      const empty = document.createElement("div");
      empty.className = "empty";
      empty.textContent = "当前分类没有发现媒体。播放视频、滚动页面或等待资源加载后再试。";
      listNode.appendChild(empty);
      updateSelectionUi();
      return;
    }

    for (const candidate of visible) {
      const row = document.createElement("div");
      row.className = "row";

      const select = document.createElement("label");
      select.className = "select";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.disabled = !candidate.directDownload;
      checkbox.checked = selectedIds.has(candidate.id);
      checkbox.title = candidate.directDownload ? "加入批量下载" : "流媒体需交给 Galaxy";
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selectedIds.add(candidate.id);
        else selectedIds.delete(candidate.id);
        updateSelectionUi();
      });
      select.appendChild(checkbox);

      const info = document.createElement("div");
      info.className = "info";
      const title = document.createElement("div");
      title.className = "title";
      const typeBadge = document.createElement("span");
      typeBadge.className = `type ${candidate.mediaKind}`;
      typeBadge.textContent = mediaLabel(candidate.mediaKind);
      const quality = document.createElement("strong");
      quality.textContent = candidate.qualityLabel || "质量未知";
      title.append(typeBadge, quality);

      const meta = document.createElement("div");
      meta.className = "meta";
      const source = document.createElement("span");
      source.textContent = sourceLabel(candidate.source);
      const rank = document.createElement("span");
      rank.textContent = `优先级 ${Number(candidate.rankScore) || 0}`;
      meta.append(source, rank);

      const label = document.createElement("div");
      label.className = "label";
      label.textContent = candidate.label || "未命名媒体源";
      info.append(title, meta, label);

      const actions = document.createElement("div");
      actions.className = "actions";
      if (candidate.directDownload) {
        const direct = document.createElement("button");
        direct.type = "button";
        direct.textContent = "下载";
        direct.addEventListener("click", () => void downloadOne(candidate));
        actions.appendChild(direct);
      }
      const galaxy = document.createElement("button");
      galaxy.type = "button";
      galaxy.className = "primary";
      galaxy.textContent = candidate.mediaKind === "hls" || candidate.mediaKind === "dash" ? "Galaxy 解析" : "Galaxy";
      galaxy.addEventListener("click", () => void handoffCandidate(candidate));
      actions.appendChild(galaxy);

      row.append(select, info, actions);
      listNode.appendChild(row);
    }
    updateSelectionUi();
  }

  async function refreshCandidates() {
    setStatus("正在读取当前页面候选源…");
    try {
      const response = await chrome.runtime.sendMessage({ type: "galaxy:get-candidates" });
      candidates = response?.ok && Array.isArray(response.candidates) ? response.candidates : [];
      const validIds = new Set(candidates.filter((candidate) => candidate.directDownload).map((candidate) => candidate.id));
      for (const id of [...selectedIds]) if (!validIds.has(id)) selectedIds.delete(id);
      renderTabs();
      renderRows();
      setStatus(`已加载 ${candidates.length} 个候选源；真实 URL 不会显示在页面 UI 中。`, "success");
    } catch (error) {
      candidates = [];
      renderTabs();
      renderRows();
      setStatus(String(error?.message || error), "error");
    }
  }

  function closeBrowser() {
    if (dialog) dialog.classList.remove("open");
  }

  function toggleBrowser() {
    install();
    const opening = !dialog.classList.contains("open");
    dialog.classList.toggle("open", opening);
    if (opening) void refreshCandidates();
  }

  function install() {
    if (host && document.documentElement.contains(host)) return;
    host = document.createElement("div");
    host.id = HOST_ID;
    host.style.cssText = "all:initial;position:fixed;inset:0;z-index:2147483646;pointer-events:none;";
    shadow = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = `
      :host{all:initial}*{box-sizing:border-box}
      .dialog{display:none;pointer-events:auto;position:fixed;inset:0;background:rgba(2,6,23,.54);font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;color:#e5edf7;padding:32px}
      .dialog.open{display:flex;align-items:center;justify-content:center}
      .shell{width:min(920px,100%);max-height:min(760px,calc(100vh - 64px));display:flex;flex-direction:column;overflow:hidden;background:#0b1220;border:1px solid #263348;border-radius:16px;box-shadow:0 28px 100px rgba(0,0,0,.48)}
      .header{display:flex;align-items:center;gap:12px;padding:15px 17px;border-bottom:1px solid #202c3d}.header strong{font-size:15px}.header span{color:#8fa1b7;flex:1}.header button{border:0;background:transparent;color:#94a3b8;font-size:24px;cursor:pointer}
      .tabs{display:flex;gap:6px;padding:10px 14px;border-bottom:1px solid #202c3d;overflow:auto}.tabs button,.toolbar button,.actions button{border:1px solid #34445c;background:#172238;color:#dce8f6;border-radius:8px;padding:7px 9px;font:600 12px/1 system-ui;cursor:pointer;white-space:nowrap}.tabs button.active{background:#e2e8f0;color:#0f172a;border-color:#e2e8f0}
      .toolbar{display:flex;align-items:center;gap:7px;padding:10px 14px;background:#0e1728;border-bottom:1px solid #202c3d}.toolbar .summary{flex:1;color:#8fa1b7}.toolbar button.primary,.actions button.primary{background:#0ea5e9;border-color:#0ea5e9;color:white}.toolbar button:disabled,.actions button:disabled{opacity:.45;cursor:default}
      .list{min-height:180px;max-height:520px;overflow:auto;padding:7px}.row{display:grid;grid-template-columns:28px minmax(0,1fr) auto;gap:10px;align-items:center;padding:10px;border-radius:11px}.row:hover{background:#121d30}.select{display:flex;align-items:center;justify-content:center}.select input{width:15px;height:15px;accent-color:#0ea5e9}
      .info{min-width:0}.title{display:flex;align-items:center;gap:8px}.title strong{font-size:13px;color:#f8fafc}.type{display:inline-flex;padding:2px 6px;border-radius:999px;background:#1e293b;color:#cbd5e1;font-size:10px;font-weight:700}.type.video{color:#bae6fd}.type.audio{color:#ddd6fe}.type.image{color:#bbf7d0}.type.hls,.type.dash{color:#fde68a}
      .meta{display:flex;gap:10px;color:#7f93aa;font-size:11px;margin-top:3px}.label{color:#9badc1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:580px;margin-top:2px}.actions{display:flex;gap:6px}.empty{padding:36px 18px;text-align:center;color:#8fa1b7}
      .status{padding:9px 14px;border-top:1px solid #202c3d;color:#7dd3fc;background:#09111e}.status[data-kind="success"]{color:#86efac}.status[data-kind="error"]{color:#fca5a5}.status[data-kind="warn"]{color:#fde68a}
      @media(max-width:680px){.dialog{padding:12px}.shell{max-height:calc(100vh - 24px)}.row{grid-template-columns:24px minmax(0,1fr)}.actions{grid-column:2}.label{max-width:58vw}.header span{display:none}}
    `;

    dialog = document.createElement("div");
    dialog.className = "dialog";
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) closeBrowser();
    });

    const shell = document.createElement("div");
    shell.className = "shell";
    const header = document.createElement("div");
    header.className = "header";
    const heading = document.createElement("strong");
    heading.textContent = "Galaxy 媒体候选浏览器";
    const subtitle = document.createElement("span");
    subtitle.textContent = "筛选、比较并批量下载当前页面公开媒体源";
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "×";
    close.addEventListener("click", closeBrowser);
    header.append(heading, subtitle, close);

    tabsNode = document.createElement("div");
    tabsNode.className = "tabs";
    const toolbar = document.createElement("div");
    toolbar.className = "toolbar";
    summaryNode = document.createElement("div");
    summaryNode.className = "summary";
    selectButton = document.createElement("button");
    selectButton.type = "button";
    selectButton.textContent = "全选当前";
    selectButton.addEventListener("click", toggleSelectVisible);
    const refresh = document.createElement("button");
    refresh.type = "button";
    refresh.textContent = "刷新";
    refresh.addEventListener("click", () => void refreshCandidates());
    batchButton = document.createElement("button");
    batchButton.type = "button";
    batchButton.className = "primary";
    batchButton.textContent = "批量下载";
    batchButton.addEventListener("click", () => void batchDownload());
    toolbar.append(summaryNode, selectButton, refresh, batchButton);

    listNode = document.createElement("div");
    listNode.className = "list";
    statusNode = document.createElement("div");
    statusNode.className = "status";
    statusNode.textContent = "等待打开候选浏览器。";

    shell.append(header, tabsNode, toolbar, listNode, statusNode);
    dialog.appendChild(shell);
    shadow.append(style, dialog);
    document.documentElement.appendChild(host);
    renderTabs();
    renderRows();
  }

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type === "galaxy:toggle-candidate-browser") {
      toggleBrowser();
      return;
    }
    if (message?.type === "galaxy:page-reset") {
      selectedIds.clear();
      candidates = [];
      if (dialog?.classList.contains("open")) void refreshCandidates();
    }
  });
})();
