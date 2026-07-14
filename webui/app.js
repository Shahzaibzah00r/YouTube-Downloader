const $ = (id) => document.getElementById(id);

const logEl = $("log");
const statusEl = $("status");
const barEl = $("bar");
const downloadBtn = $("downloadBtn");
const cancelBtn = $("cancelBtn");

let busy = false;
let paused = false;
let queueActive = false; // true only during download queue (not Fix tools / update)
let mode = "single";
let es = null;
let previewData = null;
let tableEntries = [];

function autoScrollEnabled() {
  return $("autoScroll").checked;
}

function appendLog(line, cls = "") {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  logEl.appendChild(span);
  if (autoScrollEnabled()) logEl.scrollTop = logEl.scrollHeight;
}

function setProgress(pct, speedLabel) {
  const n = Math.max(0, Math.min(100, Number(pct) || 0));
  const rounded = Math.round(n);
  barEl.style.width = `${n}%`;
  $("overallPct").textContent = `${rounded}%`;
  const speedEl = $("overallSpeed");
  if (speedEl) {
    if (paused) {
      speedEl.textContent = "Paused";
      speedEl.classList.add("is-active", "is-paused");
      return;
    }
    speedEl.classList.remove("is-paused");
    const label = (speedLabel || "").trim();
    speedEl.textContent = label || "—";
    speedEl.classList.toggle("is-active", Boolean(label));
  }
}

function formatEtaLabel(eta) {
  return eta ? `${eta} left` : "";
}

/** Keep job meta for retries after a batch finishes. */
const jobMeta = new Map();

function rememberJob(job) {
  if (!job) return;
  const id = String(job.id || job.url || "");
  const url = String(job.url || "").trim();
  if (!id || !url) return;
  jobMeta.set(id, {
    id,
    url,
    title: String(job.title || url),
  });
}

function clearItemProgress() {
  $("itemProgress").innerHTML = "";
  jobMeta.clear();
  updateRetryFailedBtn();
}

function ensureItemRow(id, title, url) {
  let row = [...document.querySelectorAll("[data-job-id]")].find(
    (el) => el.dataset.jobId === id
  );
  if (row) {
    if (url) row.dataset.url = url;
    if (title) row.querySelector(".t").textContent = title;
    return row;
  }
  row = document.createElement("div");
  row.className = "item-progress";
  row.dataset.jobId = id;
  if (url) row.dataset.url = url;
  row.innerHTML = `
    <div class="item-title">
      <span class="t">${escapeHtml(title || id)}</span>
      <span class="item-meta">
        <span class="s"></span>
        <span class="e"></span>
        <span class="p">0%</span>
        <button type="button" class="btn ghost tiny row-retry hidden" data-label="Retry">Retry</button>
      </span>
    </div>
    <div class="meter-track">
      <div class="meter-fill" style="width:0%"></div>
    </div>
  `;
  const retryBtn = row.querySelector(".row-retry");
  retryBtn.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    retryJobs([id], retryBtn);
  });
  $("itemProgress").appendChild(row);
  return row;
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function updateItemProgress(msg) {
  const row = ensureItemRow(msg.id, msg.title, msg.url);
  if (msg.url) rememberJob({ id: msg.id, url: msg.url, title: msg.title });
  const pct = Math.max(0, Math.min(100, Number(msg.value) || 0));
  const rounded = Math.round(pct);
  row.querySelector(".t").textContent = msg.title || msg.id;
  row.querySelector(".p").textContent =
    msg.state === "error" ? "Failed" : `${rounded}%`;
  const speedEl = row.querySelector(".s");
  const etaEl = row.querySelector(".e");
  const running = msg.state === "running";
  if (paused && running) {
    if (speedEl) {
      speedEl.textContent = "Paused";
      speedEl.classList.remove("hidden");
    }
    if (etaEl) {
      etaEl.textContent = "";
      etaEl.classList.add("hidden");
    }
  } else {
    if (speedEl) {
      const rate = running && msg.speed ? String(msg.speed) : "";
      speedEl.textContent = rate;
      speedEl.classList.toggle("hidden", !rate);
    }
    if (etaEl) {
      const eta = running && msg.eta ? formatEtaLabel(msg.eta) : "";
      etaEl.textContent = eta;
      etaEl.classList.toggle("hidden", !eta);
    }
  }
  row.querySelector(".meter-fill").style.width = `${pct}%`;
  row.classList.toggle("done", msg.state === "done");
  row.classList.toggle("error", msg.state === "error");
  row.classList.toggle("running", running);
  row.classList.toggle("is-paused", paused && running);
  const retryBtn = row.querySelector(".row-retry");
  if (retryBtn) {
    const show = msg.state === "error" && !busy;
    retryBtn.classList.toggle("hidden", !show);
    if (!show && retryBtn.classList.contains("is-loading")) {
      setButtonLoading(retryBtn, false);
    }
  }
  updateRetryFailedBtn();
}

function failedJobs() {
  const jobs = [];
  for (const row of $("itemProgress").querySelectorAll(".item-progress.error")) {
    const id = row.dataset.jobId;
    const meta = jobMeta.get(id);
    const url = (meta && meta.url) || row.dataset.url;
    if (!url) continue;
    jobs.push({
      id,
      url,
      title: (meta && meta.title) || row.querySelector(".t")?.textContent || url,
    });
  }
  return jobs;
}

function updateRetryFailedBtn() {
  const btn = $("retryFailedBtn");
  if (!btn) return;
  const n = failedJobs().length;
  const show = !busy && n > 0;
  btn.classList.toggle("hidden", !show);
  btn.disabled = !show;
  if (!btn.dataset.label) btn.dataset.label = "Retry failed";
  btn.textContent = n > 1 ? `Retry failed (${n})` : "Retry failed";
  btn.dataset.label = btn.textContent;
}

async function retryJobs(ids, triggerBtn) {
  if (busy) return;
  const wanted = new Set((ids || []).map(String));
  const jobs = failedJobs().filter((j) => !wanted.size || wanted.has(String(j.id)));
  if (!jobs.length) {
    statusEl.textContent = "No failed items to retry";
    return;
  }
  await startDownload(jobs, triggerBtn || $("retryFailedBtn"));
}

function setConcurrencyDefault(itemCount) {
  const input = $("concurrency");
  const n = Number(itemCount) || 1;
  if (n <= 1) {
    input.value = "1";
    $("concurrencyHint").textContent = "1 at a time";
  } else {
    input.value = "2";
    $("concurrencyHint").textContent = `${n} items · default 2 (max 6)`;
  }
}

function getConcurrency() {
  let n = parseInt($("concurrency").value, 10);
  if (Number.isNaN(n) || n < 1) n = 1;
  if (n > 6) n = 6;
  $("concurrency").value = String(n);
  return n;
}

function selectedJobs() {
  const jobs = [];
  const seen = new Set();
  // Prefer tableEntries so filter-hidden checked rows still download
  if (tableEntries.length) {
    for (const item of tableEntries) {
      if (item._checked === false) continue;
      const url = item.url;
      const key = normalizeUrlKey(url);
      if (!url || !key || seen.has(key)) continue;
      seen.add(key);
      jobs.push({
        url,
        title: item.title || url,
        id: item.id || url,
      });
    }
    return jobs;
  }
  for (const b of $("playlistList").querySelectorAll('input[type="checkbox"]:checked')) {
    const url = b.value;
    const key = normalizeUrlKey(url);
    if (!url || !key || seen.has(key)) continue;
    seen.add(key);
    jobs.push({
      url,
      title: b.dataset.title || url,
      id: b.dataset.id || url,
    });
  }
  return jobs;
}

function setButtonLoading(btn, loading, loadingText) {
  if (!btn) return;
  if (loading) {
    if (!btn.dataset.label) {
      btn.dataset.label = (btn.querySelector(".btn-label")?.textContent || btn.textContent || "").trim();
    }
    const label = loadingText || btn.dataset.label || "Loading…";
    btn.classList.add("is-loading");
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.innerHTML = `<span class="btn-spinner" aria-hidden="true"></span><span class="btn-label">${label}</span>`;
  } else {
    const label = btn.dataset.label || "OK";
    btn.classList.remove("is-loading");
    btn.removeAttribute("aria-busy");
    btn.innerHTML = `<span class="btn-label">${label}</span>`;
  }
}

function setPauseUi(isPaused) {
  paused = Boolean(isPaused);
  const btn = $("pauseBtn");
  if (btn) {
    btn.dataset.label = paused ? "Resume" : "Pause";
    if (!btn.classList.contains("is-loading")) {
      btn.innerHTML = `<span class="btn-label">${btn.dataset.label}</span>`;
    }
  }
  $("progressPanel")?.classList.toggle("is-paused", paused);

  if (paused && queueActive) {
    // Swap Downloading… spinner for a clear Paused label
    downloadBtn.disabled = true;
    downloadBtn.classList.remove("is-loading");
    downloadBtn.removeAttribute("aria-busy");
    downloadBtn.innerHTML = `<span class="btn-label">Paused</span>`;
    const speedEl = $("overallSpeed");
    if (speedEl) {
      speedEl.textContent = "Paused";
      speedEl.classList.add("is-active", "is-paused");
    }
    $("itemProgress")
      .querySelectorAll(".item-progress:not(.done):not(.error)")
      .forEach((row) => {
        row.classList.add("is-paused");
        const s = row.querySelector(".s");
        const e = row.querySelector(".e");
        if (s) {
          s.textContent = "Paused";
          s.classList.remove("hidden");
        }
        if (e) {
          e.textContent = "";
          e.classList.add("hidden");
        }
      });
    const q = $("queueHint");
    if (q) {
      const t = (q.textContent || "").replace(/\s*·\s*paused/i, "");
      q.textContent = t ? `${t} · paused` : "Paused";
    }
  } else if (!paused && queueActive && busy) {
    setButtonLoading(downloadBtn, true, "Downloading…");
    $("overallSpeed")?.classList.remove("is-paused");
    $("itemProgress")
      .querySelectorAll(".item-progress.is-paused")
      .forEach((row) => row.classList.remove("is-paused"));
    const q = $("queueHint");
    if (q) q.textContent = (q.textContent || "").replace(/\s*·\s*paused/i, "");
  }
}

function setBusy(on) {
  busy = on;
  cancelBtn.disabled = !(on && queueActive);
  const pauseBtn = $("pauseBtn");
  if (pauseBtn) pauseBtn.disabled = !(on && queueActive);
  if (!on) {
    queueActive = false;
    setPauseUi(false);
  }
  $("fixBtn").disabled = on;
  if ($("updateBtn")) $("updateBtn").disabled = on;
  if ($("checkUpdateBtn")) $("checkUpdateBtn").disabled = on;
  $("previewBtn").disabled = on;
  $("browseBtn").disabled = on;
  $("openBtn").disabled = on;
  if (on) {
    $("progressPanel").classList.remove("hidden");
    setProgress(0);
  } else {
    setButtonLoading(downloadBtn, false);
    $("playlistList")
      .querySelectorAll("button.row-dl.is-loading")
      .forEach((b) => setButtonLoading(b, false));
    if (!$("fixBtn").classList.contains("is-loading")) {
      $("fixBtn").disabled = false;
    }
    if ($("updateBtn") && !$("updateBtn").classList.contains("is-loading")) {
      $("updateBtn").disabled = false;
    }
    if ($("checkUpdateBtn") && !$("checkUpdateBtn").classList.contains("is-loading")) {
      $("checkUpdateBtn").disabled = false;
    }
    if (!$("previewBtn").classList.contains("is-loading")) {
      $("previewBtn").disabled = false;
    }
    if (!$("browseBtn").classList.contains("is-loading")) {
      $("browseBtn").disabled = false;
    }
    if (!$("openBtn").classList.contains("is-loading")) {
      $("openBtn").disabled = false;
    }
    // Keep progress list open when there are failures so Retry is available
    const keepOpen = $("itemProgress").children.length > 0;
    $("progressPanel").classList.toggle("hidden", !keepOpen);
  }
  updateDownloadEnabled();
  updateRetryFailedBtn();
  $("playlistList")
    .querySelectorAll("button.row-dl")
    .forEach((b) => {
      if (!b.classList.contains("is-loading")) b.disabled = on;
    });
  // Toggle per-row Retry visibility with busy state
  $("itemProgress")
    .querySelectorAll(".item-progress.error .row-retry")
    .forEach((b) => b.classList.toggle("hidden", on));
}

function updateDownloadEnabled() {
  if (busy) {
    downloadBtn.disabled = true;
    return;
  }
  if (!previewData) {
    downloadBtn.disabled = true;
    return;
  }
  if (previewData.is_playlist || (previewData.entries && previewData.entries.length)) {
    downloadBtn.disabled = selectedJobs().length === 0;
  } else {
    downloadBtn.disabled = false;
  }
}

function applyTheme(theme) {
  const t = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("ytd_theme", t);
  $("themeLabel").textContent = t === "dark" ? "Light" : "Dark";
  const ico = $("themeIcon");
  ico.classList.remove("sun", "moon");
  // In dark mode, button offers Light (sun). In light mode, offers Dark (moon).
  ico.classList.add(t === "dark" ? "sun" : "moon");
}

let uiZoom = 100; // percent

function applyZoom(pct) {
  let n = parseInt(String(pct), 10);
  if (Number.isNaN(n)) n = 100;
  n = Math.max(80, Math.min(150, n));
  // Snap to 10% steps so +/- feels reliable
  n = Math.round(n / 10) * 10;
  uiZoom = n;
  localStorage.setItem("ytd_zoom", String(uiZoom));
  $("zoomPct").textContent = `${uiZoom}%`;

  const scale = uiZoom / 100;
  const root = document.documentElement;
  const shell = document.querySelector(".shell");

  // Primary: CSS zoom (WKWebView / Chromium)
  root.style.zoom = String(scale);
  document.body.style.zoom = String(scale);

  // Fallback: transform scale (some Cocoa webviews ignore zoom)
  if (shell) {
    shell.style.transform = `scale(${scale})`;
    shell.style.transformOrigin = "top center";
    shell.style.width = scale === 1 ? "" : `${100 / scale}%`;
    shell.style.maxWidth = scale === 1 ? "" : `${1180 / scale}px`;
  }
}

function normalizeUrlKey(raw) {
  let s = String(raw || "").trim();
  if (!s) return "";
  try {
    const u = new URL(s);
    const host = (u.hostname || "").replace(/^www\./, "").toLowerCase();
    // YouTube watch / short / youtu.be → video id
    if (host === "youtu.be") {
      const id = u.pathname.replace(/^\//, "").split("/")[0];
      if (id) return `yt:${id}`;
    }
    if (host === "youtube.com" || host.endsWith(".youtube.com")) {
      const v = u.searchParams.get("v");
      if (v) return `yt:${v}`;
      const parts = u.pathname.split("/").filter(Boolean);
      if (parts[0] === "shorts" && parts[1]) return `yt:${parts[1]}`;
      if (parts[0] === "embed" && parts[1]) return `yt:${parts[1]}`;
      const list = u.searchParams.get("list");
      if (parts[0] === "playlist" && list) return `ytpl:${list}`;
      if (list && !v) return `ytpl:${list}`;
    }
    // Generic: drop hash, trailing slash, lowercase host
    u.hash = "";
    let path = u.pathname.replace(/\/+$/, "") || "/";
    return `${host}${path}${u.search}`.toLowerCase();
  } catch {
    return s.toLowerCase();
  }
}

function uniqueUrls(list) {
  const out = [];
  const seen = new Set();
  for (const raw of list || []) {
    const url = String(raw || "").trim();
    if (!url) continue;
    const key = normalizeUrlKey(url);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(url);
  }
  return out;
}

function currentUrls() {
  let list;
  if (mode === "batch") {
    list = $("batch").value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  } else {
    const one = $("url").value.trim();
    list = one ? [one] : [];
  }
  return uniqueUrls(list);
}

function syncBatchField(deduped, removed) {
  if (mode !== "batch") return;
  const next = deduped.join("\n");
  if ($("batch").value.trim() !== next) {
    $("batch").value = next;
  }
  updateBatchCount();
  if (removed > 0) {
    statusEl.textContent = `Removed ${removed} duplicate URL${removed === 1 ? "" : "s"}`;
  }
}

function updateBatchCount() {
  const raw = $("batch").value
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  const n = uniqueUrls(raw).length;
  const dupes = raw.length - n;
  $("batchCount").textContent =
    dupes > 0
      ? `${n} unique URL${n === 1 ? "" : "s"} (${dupes} duplicate ignored)`
      : `${n} URL${n === 1 ? "" : "s"}`;
}

function mediaMode() {
  const video = $("optVideo").checked;
  const audio = $("optAudio").checked;
  if (video && audio) return "both";
  if (audio) return "audio";
  if (!video && !audio) $("optVideo").checked = true;
  return "video";
}

function updateMediaHints() {
  const m = mediaMode();
  const hints = {
    video: "Video selected — check Audio too for video + separate MP3",
    audio: "Audio only — saves MP3 for each selected item",
    both: "Both selected — saves video and a separate MP3 per item",
  };
  $("mediaHint").textContent =
    hints[m] + " · Get preview, then Download on a row or Download selected";
  $("qualityBox").classList.toggle("is-disabled", m === "audio");
  $("quality").disabled = m === "audio";
}

function clearPreview() {
  previewData = null;
  tableEntries = [];
  $("previewPanel").classList.add("hidden");
  $("playlistList").innerHTML = "";
  $("previewSize").classList.add("hidden");
  $("previewThumb").classList.add("hidden");
  $("previewThumb").removeAttribute("src");
  if ($("playlistFilter")) $("playlistFilter").value = "";
  if ($("estSize")) $("estSize").textContent = "—";
  updateDownloadEnabled();
}

function setMode(next) {
  mode = next;
  $("modeSingle").classList.toggle("active", mode === "single");
  $("modeBatch").classList.toggle("active", mode === "batch");
  $("singleBox").classList.toggle("hidden", mode !== "single");
  $("batchBox").classList.toggle("hidden", mode !== "batch");
  clearPreview();
  updateBatchCount();
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText || "Request failed");
  return data;
}

function updateSelectedCount() {
  const total = tableEntries.length;
  if (total) {
    const n = tableEntries.filter((i) => i._checked !== false).length;
    const visible = [...$("playlistList").querySelectorAll('input[type="checkbox"]')].length;
    $("selectedCount").textContent = filterQuery()
      ? `${n} selected · ${visible} shown · ${total} total`
      : `${n} of ${total} selected`;
  } else {
    const boxes = [...$("playlistList").querySelectorAll('input[type="checkbox"]')];
    const n = boxes.filter((b) => b.checked).length;
    $("selectedCount").textContent = `${n} of ${boxes.length} selected`;
  }
  updateEstSize();
  updateDownloadEnabled();
}

function renderHistory(items) {
  const list = $("historyList");
  if (!list) return;
  list.innerHTML = "";
  const rows = Array.isArray(items) ? items : [];
  if (!rows.length) {
    list.innerHTML = `<p class="field-note">No recent downloads yet</p>`;
    return;
  }
  for (const item of rows.slice(0, 20)) {
    const row = document.createElement("div");
    row.className = "history-row";
    const title = item.title || item.url || "Download";
    const path = item.path || item.outdir || "";
    row.innerHTML = `
      <div class="history-copy">
        <strong class="history-title" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
        <span class="history-path muted" title="${escapeHtml(path)}">${escapeHtml(path || "—")}</span>
      </div>
      <div class="history-actions">
        <button type="button" class="btn ghost tiny hist-reuse" data-label="Reuse">Reuse</button>
        <button type="button" class="btn ghost tiny hist-reveal" data-label="Reveal">Reveal</button>
      </div>
    `;
    row.querySelector(".hist-reuse").onclick = () => {
      if (item.url) {
        setMode("single");
        $("url").value = item.url;
        clearPreview();
        statusEl.textContent = "URL loaded from history";
      }
    };
    row.querySelector(".hist-reveal").onclick = async () => {
      try {
        await api("/api/reveal", {
          method: "POST",
          body: JSON.stringify({ path: item.path || "", outdir: item.outdir || $("outdir").value }),
        });
      } catch (e) {
        appendLog(String(e.message || e), "err");
      }
    };
    list.appendChild(row);
  }
}

async function refreshHistory() {
  try {
    const data = await api("/api/history");
    renderHistory(data.items || []);
  } catch {
    /* ignore */
  }
}

function selectedPlaylistUrls() {
  return [...$("playlistList").querySelectorAll('input[type="checkbox"]:checked')]
    .map((b) => b.value)
    .filter(Boolean);
}

async function startDownload(jobs, triggerBtn) {
  const list = (jobs || [])
    .map((j) => (typeof j === "string" ? { url: j, title: j, id: j } : j))
    .filter((j) => j && j.url);
  if (busy || !list.length) return;
  queueActive = true;
  setBusy(true);
  setButtonLoading(triggerBtn || downloadBtn, true, "Downloading…");
  if (triggerBtn && triggerBtn !== downloadBtn) {
    setButtonLoading(downloadBtn, true, "Downloading…");
  }
  setProgress(0);
  clearItemProgress();
  list.forEach((j) => {
    rememberJob(j);
    ensureItemRow(j.id || j.url, j.title || j.url, j.url);
  });
  const concurrency = Math.min(getConcurrency(), list.length);
  statusEl.textContent =
    list.length > 1
      ? `Queueing ${list.length} downloads (${concurrency} at once)…`
      : "Downloading…";
  appendLog("");
  appendLog(`Starting ${list.length} download(s) · concurrency=${concurrency}`, "ok");
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({
        jobs: list,
        quality: $("quality").value,
        media: mediaMode(),
        outdir: $("outdir").value,
        concurrency,
        template: ($("filenameTpl") && $("filenameTpl").value) || "title",
        subs: Boolean($("optSubs") && $("optSubs").checked),
      }),
    });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    statusEl.textContent = "Download failed to start";
    setBusy(false);
  }
}

function parseSizeToBytes(raw) {
  const m = String(raw || "").trim().match(/^([\d.]+)\s*(B|KB|MB|GB|TB)\b/i);
  if (!m) return 0;
  const n = parseFloat(m[1]);
  if (Number.isNaN(n)) return 0;
  const mult = { B: 1, KB: 1024, MB: 1024 ** 2, GB: 1024 ** 3, TB: 1024 ** 4 };
  return n * (mult[(m[2] || "B").toUpperCase()] || 0);
}

function formatBytesShort(n) {
  if (!n || n <= 0) return "";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = n;
  let i = 0;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i += 1;
  }
  return i === 0 ? `${Math.round(size)} ${units[i]}` : `${size.toFixed(1)} ${units[i]}`;
}

function updateEstSize() {
  const el = $("estSize");
  if (!el) return;
  let total = 0;
  let known = 0;
  let selected = 0;
  const source = tableEntries.length
    ? tableEntries.filter((i) => i._checked !== false)
    : null;
  if (source) {
    selected = source.length;
    for (const item of source) {
      const bytes = parseSizeToBytes(item.filesize || "");
      if (bytes > 0) {
        total += bytes;
        known += 1;
      }
    }
  } else {
    for (const b of $("playlistList").querySelectorAll('input[type="checkbox"]:checked')) {
      selected += 1;
      const bytes = parseSizeToBytes(b.dataset.size || "");
      if (bytes > 0) {
        total += bytes;
        known += 1;
      }
    }
  }
  if (!selected) {
    el.textContent = "—";
    return;
  }
  if (!known) {
    el.textContent = "Size unknown";
    return;
  }
  const label = formatBytesShort(total);
  el.textContent =
    known === selected ? `Est. ${label}` : `Est. ~${label} (${known} sized)`;
}

function filterQuery() {
  return (($("playlistFilter") && $("playlistFilter").value) || "").trim().toLowerCase();
}

function renderTable(entries) {
  tableEntries = entries || [];
  const list = $("playlistList");
  list.innerHTML = "";
  const q = filterQuery();
  let shown = 0;

  for (const item of tableEntries) {
    const hay = `${item.title || ""} ${item.uploader || ""} ${item.source || ""}`.toLowerCase();
    if (q && !hay.includes(q)) continue;
    shown += 1;
    const tr = document.createElement("tr");

    const tdCheck = document.createElement("td");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "row-check";
    cb.checked = item._checked !== false;
    cb.value = item.url;
    cb.dataset.title = item.title || item.url;
    cb.dataset.id = item.id || `vid-${item.index || ""}-${item.url}`;
    cb.dataset.size = item.filesize || "";
    cb.addEventListener("change", () => {
      item._checked = cb.checked;
      updateSelectedCount();
    });
    tdCheck.appendChild(cb);

    const tdNum = document.createElement("td");
    tdNum.textContent = String(item.index ?? "");

    const tdThumb = document.createElement("td");
    tdThumb.className = "thumb-cell";
    const img = document.createElement("img");
    img.className = "thumb";
    img.alt = "Thumbnail";
    img.loading = "lazy";
    img.decoding = "async";
    if (item.thumbnail) img.src = item.thumbnail;
    tdThumb.appendChild(img);

    const tdTitle = document.createElement("td");
    tdTitle.className = "title-cell";
    tdTitle.textContent = item.title || "Untitled";
    tdTitle.title = item.title || "";

    const tdInfo = document.createElement("td");
    tdInfo.className = "info-cell";
    const bits = [];
    if (item.duration) bits.push(item.duration);
    if (item.filesize) bits.push(item.filesize);
    if (item.uploader) bits.push(item.uploader);
    if (item.source && item.source !== item.title) bits.push(item.source);
    tdInfo.textContent = bits.join(" · ") || "—";
    tdInfo.title = bits.join(" · ") || "";

    const tdDl = document.createElement("td");
    tdDl.className = "col-dl";
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn row-dl";
    btn.dataset.label = "Download";
    btn.innerHTML = `<span class="btn-label">Download</span>`;
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startDownload(
        [
          {
            url: item.url,
            title: item.title || item.url,
            id: item.id || `vid-${item.index || ""}-${item.url}`,
          },
        ],
        btn
      );
    });
    tdDl.appendChild(btn);

    tr.append(tdCheck, tdNum, tdThumb, tdTitle, tdInfo, tdDl);
    list.appendChild(tr);
  }
  if (q) {
    $("playlistLabel").textContent = `Showing ${shown} of ${tableEntries.length}`;
  }
  updateSelectedCount();
}

function entriesPreviewSize(data) {
  const entries = data.entries || [];
  if (entries.length === 1 && entries[0].filesize) return entries[0].filesize;
  return null;
}

function showPreview(data) {
  previewData = data;
  $("previewPanel").classList.remove("hidden");

  $("previewTitle").textContent = data.title || "Untitled";
  const bits = [];
  if (data.kind) bits.push(data.kind);
  if (data.count != null && (data.is_playlist || data.batch_sources)) {
    bits.push(`${data.count} video${data.count === 1 ? "" : "s"}`);
  }
  if (data.batch_sources) bits.push(`${data.batch_sources} URLs`);
  if (data.duration) bits.push(data.duration);
  if (data.uploader) bits.push(data.uploader);
  $("previewSub").textContent = bits.join(" · ") || "Ready";

  const sizeEl = $("previewSize");
  const sizeText = data.filesize || entriesPreviewSize(data);
  if (sizeText) {
    sizeEl.textContent = sizeText;
    sizeEl.classList.remove("hidden");
  } else {
    sizeEl.classList.add("hidden");
  }

  const img = $("previewThumb");
  const thumb =
    data.thumbnail ||
    (data.entries && data.entries[0] && data.entries[0].thumbnail) ||
    null;
  if (thumb) {
    img.src = thumb;
    img.classList.remove("hidden");
  } else {
    img.removeAttribute("src");
    img.classList.add("hidden");
  }

  let entries = data.entries || [];
  if (!entries.length && data.url) {
    entries = [
      {
        index: 1,
        title: data.title || "Video",
        url: data.url,
        thumbnail: data.thumbnail,
        duration: data.duration,
        filesize: data.filesize,
        uploader: data.uploader,
      },
    ];
  }

  // Filter duplicate video rows (same YouTube id / URL)
  const seen = new Set();
  entries = entries.filter((item) => {
    const key = normalizeUrlKey(item.url || item.id || "");
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  entries.forEach((item, i) => {
    item.index = i + 1;
  });

  $("playlistLabel").textContent =
    entries.length > 1
      ? `${entries.length} videos — Download on a row or Download selected`
      : "Use Download on the row or Download selected";
  $("playlistTools").classList.toggle("hidden", entries.length <= 1);

  renderTable(entries);
  setConcurrencyDefault(entries.length);
  updateDownloadEnabled();
}

function urlsForDownload() {
  return selectedJobs().map((j) => j.url);
}

function jobsForDownload() {
  const jobs = selectedJobs();
  if (jobs.length) return jobs;
  if (previewData && previewData.url) {
    return [
      {
        url: previewData.url,
        title: previewData.title || previewData.url,
        id: "single-1",
      },
    ];
  }
  return [];
}

let pendingUpdate = null;
let appVersion = "";

function hideUpdateModal() {
  $("updateModal")?.classList.add("hidden");
}

function showUpdateModal(info) {
  pendingUpdate = info;
  const modal = $("updateModal");
  if (!modal) return;
  $("updateModalTitle").textContent = "Update available";
  $("updateModalBody").textContent =
    `YTDownloader ${info.latest} is available (you have ${info.current}). ` +
    `Install now? macOS may ask for your password to update Applications.`;
  $("updateModalMeta").textContent = info.asset_name
    ? `${info.asset_name} · ${info.arch}`
    : `${info.arch} build`;
  modal.classList.remove("hidden");
}

async function checkAppUpdate({ interactive = false, forceModal = false } = {}) {
  const btn = $("checkUpdateBtn");
  if (interactive && btn) setButtonLoading(btn, true, "Checking…");
  try {
    const info = await api("/api/check-update");
    if (!info.ok) {
      if (interactive) {
        statusEl.textContent = info.error || "Could not check for updates";
        appendLog(info.error || "Update check failed", "err");
      }
      return info;
    }
    appVersion = info.current || appVersion;
    if ($("archPill") && appVersion) {
      const archBit = $("archPill").textContent.split("·")[0].trim();
      // keep existing ready state text pattern when possible
      if (!$("archPill").dataset.base) {
        $("archPill").dataset.base = $("archPill").textContent;
      }
    }
    if (info.update_available && info.asset_url) {
      const skipKey = `ytd_skip_${info.latest}`;
      const skipped = localStorage.getItem(skipKey) === "1";
      if (interactive || forceModal || !skipped) {
        showUpdateModal(info);
      }
      statusEl.textContent = `Update available: v${info.latest}`;
      appendLog(`Update available: v${info.current} → v${info.latest}`, "ok");
    } else if (interactive) {
      statusEl.textContent = `You're on the latest version (v${info.current})`;
      appendLog(`Up to date · v${info.current}`, "ok");
      hideUpdateModal();
    }
    return info;
  } catch (e) {
    if (interactive) {
      statusEl.textContent = String(e.message || e);
      appendLog(String(e.message || e), "err");
    }
    return null;
  } finally {
    if (interactive && btn) {
      setButtonLoading(btn, false);
      btn.disabled = false;
    }
  }
}

async function installPendingUpdate() {
  if (!pendingUpdate || !pendingUpdate.asset_url) {
    statusEl.textContent = "No update selected";
    return;
  }
  hideUpdateModal();
  const btn = $("checkUpdateBtn");
  const installBtn = $("updateInstallBtn");
  setButtonLoading(btn, true, "Updating…");
  if (installBtn) setButtonLoading(installBtn, true, "Installing…");
  statusEl.textContent = "Downloading and installing update…";
  appendLog("Installing app update (clears Gatekeeper quarantine automatically)…", "muted");
  try {
    await api("/api/install-update", {
      method: "POST",
      body: JSON.stringify({
        asset_url: pendingUpdate.asset_url,
        asset_name: pendingUpdate.asset_name || "",
      }),
    });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    statusEl.textContent = String(e.message || e);
    setButtonLoading(btn, false);
    btn.disabled = false;
    if (installBtn) {
      setButtonLoading(installBtn, false);
      installBtn.disabled = false;
    }
  }
}

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    appVersion = h.version || appVersion;
    $("archPill").textContent = appVersion
      ? `${h.arch} · v${appVersion}`
      : `${h.arch} · ${h.ready ? "ready" : "tools missing"}`;
    if (!h.ready) {
      $("archPill").textContent = `${h.arch} · tools missing`;
    }
    if (!$("outdir").value) $("outdir").value = h.default_dir || "";
    if (h.ready) {
      statusEl.textContent = "Ready — paste URL(s) and click Get preview";
      appendLog(`Ready · yt-dlp=${h.yt_dlp}`, "ok");
      appendLog(`ffmpeg=${h.ffmpeg}`, "muted");
      if (appVersion) appendLog(`App v${appVersion}`, "muted");
    } else {
      statusEl.textContent = `Missing ${h.missing.join(", ")} — click Fix tools`;
      appendLog("Tools missing. Click Fix tools.", "err");
    }
  } catch (e) {
    statusEl.textContent = String(e.message || e);
    appendLog(String(e.message || e), "err");
  }
}

function listenEvents() {
  if (es) es.close();
  es = new EventSource("/api/events");
  es.onmessage = (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === "log") appendLog(msg.line, msg.cls || "");
    if (msg.type === "status") statusEl.textContent = msg.text;
    if (msg.type === "paused") setPauseUi(Boolean(msg.value));
    if (msg.type === "app_update" && msg.result && msg.result.relaunch) {
      statusEl.textContent = msg.result.message || "Relaunching…";
      appendLog("Closing old window for update…", "muted");
      // Best-effort close of the pywebview window; shell also quits the app
      setTimeout(() => {
        try {
          window.close();
        } catch {
          /* ignore */
        }
      }, 400);
    }
    if (msg.type === "progress") setProgress(msg.value, msg.speed);
    if (msg.type === "queue") {
      const text = msg.text || "";
      $("queueHint").textContent =
        paused && text && !/paused/i.test(text) ? `${text} · paused` : text;
    }
    if (msg.type === "history" && Array.isArray(msg.items)) renderHistory(msg.items);
    if (msg.type === "items_init" && Array.isArray(msg.items)) {
      clearItemProgress();
      msg.items.forEach((it) => {
        rememberJob(it);
        ensureItemRow(it.id, it.title, it.url);
      });
    }
    if (msg.type === "item") updateItemProgress(msg);
    if (msg.type === "done") {
      setBusy(false);
      setButtonLoading($("fixBtn"), false);
      $("fixBtn").disabled = false;
      if ($("updateBtn")) {
        setButtonLoading($("updateBtn"), false);
        $("updateBtn").disabled = false;
      }
      const speedEl = $("overallSpeed");
      if (speedEl) {
        speedEl.textContent = "—";
        speedEl.classList.remove("is-active");
      }
      updateRetryFailedBtn();
      const fails = failedJobs().length;
      if (fails) {
        $("queueHint").textContent = `${fails} failed — retry below`;
      }
      refreshHistory();
    }
    if (msg.type === "error") {
      setBusy(false);
      setButtonLoading($("fixBtn"), false);
      $("fixBtn").disabled = false;
      if ($("updateBtn")) {
        setButtonLoading($("updateBtn"), false);
        $("updateBtn").disabled = false;
      }
      appendLog(msg.text, "err");
      updateRetryFailedBtn();
    }
  };
}

$("themeBtn").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
};

$("zoomReset").onclick = (e) => {
  e.preventDefault();
  applyZoom(100);
};

// ⌘+/⌘−/⌘0 (and Ctrl on non-Mac) — same as browser page zoom
window.addEventListener(
  "keydown",
  (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (!mod) return;
    const key = e.key;
    const code = e.code;
    const zoomIn =
      key === "+" ||
      key === "=" ||
      code === "Equal" ||
      code === "NumpadAdd";
    const zoomOut = key === "-" || key === "−" || code === "Minus" || code === "NumpadSubtract";
    const zoomReset = key === "0" || code === "Digit0" || code === "Numpad0";
    if (zoomIn) {
      e.preventDefault();
      e.stopPropagation();
      applyZoom(uiZoom + 10);
    } else if (zoomOut) {
      e.preventDefault();
      e.stopPropagation();
      applyZoom(uiZoom - 10);
    } else if (zoomReset) {
      e.preventDefault();
      e.stopPropagation();
      applyZoom(100);
    }
  },
  true
);

$("modeSingle").onclick = () => setMode("single");
$("modeBatch").onclick = () => setMode("batch");
$("batch").addEventListener("input", () => {
  updateBatchCount();
  clearPreview();
});

$("batch").addEventListener("blur", () => {
  const raw = $("batch").value
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
  const deduped = uniqueUrls(raw);
  syncBatchField(deduped, raw.length - deduped.length);
});
$("url").addEventListener("input", clearPreview);

$("autoScroll").addEventListener("change", () => {
  localStorage.setItem("ytd_autoscroll", $("autoScroll").checked ? "1" : "0");
});

async function readClipboardText() {
  // Native app: WKWebView blocks navigator.clipboard — use backend pbpaste
  try {
    const data = await api("/api/clipboard");
    if (data && typeof data.text === "string" && data.text.trim()) {
      return data.text;
    }
  } catch {
    /* fall through */
  }
  try {
    if (navigator.clipboard && navigator.clipboard.readText) {
      const text = await navigator.clipboard.readText();
      if (text && text.trim()) return text;
    }
  } catch {
    /* fall through */
  }
  return "";
}

function applyPastedText(text) {
  const raw = String(text || "").trim();
  if (!raw) {
    statusEl.textContent = "Clipboard is empty";
    return;
  }
  if (mode === "batch") {
    const cur = $("batch").value.trim();
    const merged = `${cur}\n${raw}`
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    const before = merged.length;
    const deduped = uniqueUrls(merged);
    $("batch").value = deduped.join("\n");
    updateBatchCount();
    statusEl.textContent =
      before > deduped.length
        ? `Pasted — removed ${before - deduped.length} duplicate(s)`
        : `Pasted ${deduped.length - (cur ? cur.split(/\r?\n/).filter(Boolean).length : 0)} URL(s)`;
  } else {
    $("url").value = raw.split(/\r?\n/)[0].trim();
    statusEl.textContent = "URL pasted";
  }
  clearPreview();
}

$("pasteBtn").onclick = async () => {
  const btn = $("pasteBtn");
  setButtonLoading(btn, true, "Pasting…");
  try {
    const text = await readClipboardText();
    applyPastedText(text);
  } catch (e) {
    statusEl.textContent = "Paste failed — try ⌘V";
    appendLog(String(e.message || e), "err");
  } finally {
    setButtonLoading(btn, false);
    btn.disabled = false;
  }
};

$("previewBtn").onclick = async () => {
  if (mode === "batch") {
    const raw = $("batch").value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    const deduped = uniqueUrls(raw);
    syncBatchField(deduped, raw.length - deduped.length);
  }
  const urls = currentUrls();
  if (!urls.length) {
    statusEl.textContent = "Paste a playlist or video URL first";
    return;
  }
  statusEl.textContent =
    urls.length > 1 ? `Fetching preview for ${urls.length} URLs…` : "Fetching preview…";
  setButtonLoading($("previewBtn"), true, "Loading…");
  $("downloadBtn").disabled = true;
  $("browseBtn").disabled = true;
  try {
    const data = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ urls }),
    });
    showPreview(data);
    if (data.warnings && data.warnings.length) {
      data.warnings.forEach((w) => appendLog(w, "err"));
    }
    statusEl.textContent = data.is_playlist
      ? `Found ${data.count || 0} items — pick what to download`
      : "Ready — click Download on the row";
  } catch (e) {
    clearPreview();
    statusEl.textContent = String(e.message || e);
    appendLog(String(e.message || e), "err");
  } finally {
    setButtonLoading($("previewBtn"), false);
    if (!busy) {
      $("previewBtn").disabled = false;
      $("browseBtn").disabled = false;
      updateDownloadEnabled();
    }
  }
};

$("selectAllBtn").onclick = () => {
  tableEntries.forEach((item) => {
    item._checked = true;
  });
  $("playlistList").querySelectorAll('input[type="checkbox"]').forEach((b) => {
    b.checked = true;
  });
  updateSelectedCount();
};

$("selectNoneBtn").onclick = () => {
  tableEntries.forEach((item) => {
    item._checked = false;
  });
  $("playlistList").querySelectorAll('input[type="checkbox"]').forEach((b) => {
    b.checked = false;
  });
  updateSelectedCount();
};

if ($("playlistFilter")) {
  $("playlistFilter").addEventListener("input", () => {
    if (tableEntries.length) renderTable(tableEntries);
  });
}

$("browseBtn").onclick = async () => {
  try {
    statusEl.textContent = "Choose a folder…";
    setButtonLoading($("browseBtn"), true, "Browsing…");
    const data = await api("/api/pick-folder", {
      method: "POST",
      body: JSON.stringify({ path: $("outdir").value }),
    });
    if (data.cancelled) {
      statusEl.textContent = "Folder selection cancelled";
      return;
    }
    if (data.path) {
      $("outdir").value = data.path;
      statusEl.textContent = `Save folder → ${data.path}`;
    }
  } catch (e) {
    appendLog(String(e.message || e), "err");
    statusEl.textContent = String(e.message || e);
  } finally {
    setButtonLoading($("browseBtn"), false);
    if (!busy) $("browseBtn").disabled = false;
  }
};

$("outdir").onclick = () => $("browseBtn").click();

$("folderBtn").onclick = async () => {
  const h = await api("/api/health");
  $("outdir").value = h.default_dir;
};

$("openBtn").onclick = async () => {
  try {
    setButtonLoading($("openBtn"), true, "Opening…");
    await api("/api/open-folder", {
      method: "POST",
      body: JSON.stringify({ path: $("outdir").value }),
    });
  } catch (e) {
    appendLog(String(e.message || e), "err");
  } finally {
    setButtonLoading($("openBtn"), false);
    if (!busy) $("openBtn").disabled = false;
  }
};

$("clearBtn").onclick = () => {
  logEl.textContent = "";
};

$("fixBtn").onclick = async () => {
  if (busy) return;
  setButtonLoading($("fixBtn"), true, "Installing…");
  setBusy(true);
  // Keep install spinner; don't show download spinner for this task
  setButtonLoading(downloadBtn, false);
  downloadBtn.disabled = true;
  statusEl.textContent = "Installing yt-dlp and ffmpeg…";
  appendLog("Running brew install yt-dlp ffmpeg…", "muted");
  try {
    await api("/api/fix-tools", { method: "POST", body: "{}" });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    setBusy(false);
    setButtonLoading($("fixBtn"), false);
    $("fixBtn").disabled = false;
  }
};

$("updateBtn").onclick = async () => {
  if (busy) return;
  setButtonLoading($("updateBtn"), true, "Updating…");
  setBusy(true);
  setButtonLoading(downloadBtn, false);
  downloadBtn.disabled = true;
  statusEl.textContent = "Updating yt-dlp…";
  appendLog("Updating yt-dlp…", "muted");
  try {
    await api("/api/update-ytdlp", { method: "POST", body: "{}" });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    setBusy(false);
    setButtonLoading($("updateBtn"), false);
    $("updateBtn").disabled = false;
  }
};

$("checkUpdateBtn").onclick = async () => {
  if (busy) return;
  await checkAppUpdate({ interactive: true, forceModal: true });
};

$("updateLaterBtn").onclick = () => {
  if (pendingUpdate && pendingUpdate.latest) {
    localStorage.setItem(`ytd_skip_${pendingUpdate.latest}`, "1");
  }
  hideUpdateModal();
  statusEl.textContent = "Update postponed";
};

$("updateInstallBtn").onclick = () => installPendingUpdate();

$("updateOpenReleaseBtn").onclick = () => {
  const url =
    (pendingUpdate && pendingUpdate.release_url) ||
    "https://github.com/Shahzaibzah00r/YouTube-Downloader/releases/latest";
  window.open(url, "_blank", "noopener,noreferrer");
};

$("pauseBtn").onclick = async () => {
  if (!busy) return;
  try {
    if (paused) {
      await api("/api/resume", { method: "POST", body: "{}" });
      setPauseUi(false);
    } else {
      await api("/api/pause", { method: "POST", body: "{}" });
      setPauseUi(true);
    }
  } catch (e) {
    appendLog(String(e.message || e), "err");
  }
};

$("cancelBtn").onclick = async () => {
  try {
    await api("/api/cancel", { method: "POST", body: "{}" });
    statusEl.textContent = "Cancelling…";
    setPauseUi(false);
  } catch (e) {
    appendLog(String(e.message || e), "err");
  }
};

if ($("refreshHistoryBtn")) {
  $("refreshHistoryBtn").onclick = () => refreshHistory();
}

if ($("filenameTpl")) {
  $("filenameTpl").value = localStorage.getItem("ytd_template") || "title";
  $("filenameTpl").addEventListener("change", () => {
    localStorage.setItem("ytd_template", $("filenameTpl").value);
  });
}
if ($("optSubs")) {
  $("optSubs").checked = localStorage.getItem("ytd_subs") === "1";
  $("optSubs").addEventListener("change", () => {
    localStorage.setItem("ytd_subs", $("optSubs").checked ? "1" : "0");
  });
}

$("retryFailedBtn").onclick = async () => {
  if (busy) return;
  setButtonLoading($("retryFailedBtn"), true, "Retrying…");
  await retryJobs(null, $("retryFailedBtn"));
};

$("downloadBtn").onclick = async () => {
  if (busy) return;
  if (!previewData) {
    statusEl.textContent = "Click Get preview first";
    return;
  }
  const jobs = jobsForDownload();
  if (!jobs.length) {
    statusEl.textContent = "Select at least one video";
    return;
  }
  await startDownload(jobs, downloadBtn);
};

$("url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("previewBtn").click();
});

$("optVideo").addEventListener("change", updateMediaHints);
$("optAudio").addEventListener("change", updateMediaHints);

// Seed button labels for loading state restore
["previewBtn", "downloadBtn", "cancelBtn", "pauseBtn", "openBtn", "fixBtn", "updateBtn", "checkUpdateBtn", "browseBtn", "folderBtn", "pasteBtn", "updateInstallBtn"].forEach((id) => {
  const el = $(id);
  if (el && !el.dataset.label) el.dataset.label = el.textContent.trim();
});

// Drag-and-drop URLs onto the window
(function setupDrop() {
  const overlay = $("dropOverlay");
  let dragDepth = 0;
  const hasFilesOrUri = (e) => {
    const types = e.dataTransfer && e.dataTransfer.types
      ? [...e.dataTransfer.types]
      : [];
    return types.includes("text/uri-list") || types.includes("text/plain") || types.includes("Files");
  };
  window.addEventListener("dragenter", (e) => {
    if (!hasFilesOrUri(e)) return;
    e.preventDefault();
    dragDepth += 1;
    if (overlay) overlay.classList.remove("hidden");
  });
  window.addEventListener("dragleave", (e) => {
    if (!hasFilesOrUri(e)) return;
    e.preventDefault();
    dragDepth = Math.max(0, dragDepth - 1);
    if (dragDepth === 0 && overlay) overlay.classList.add("hidden");
  });
  window.addEventListener("dragover", (e) => {
    if (!hasFilesOrUri(e)) return;
    e.preventDefault();
  });
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    if (overlay) overlay.classList.add("hidden");
    const text =
      (e.dataTransfer && (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain"))) ||
      "";
    const urls = String(text)
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => /^https?:\/\//i.test(s));
    if (!urls.length) {
      statusEl.textContent = "Drop a URL (http/https)";
      return;
    }
    if (urls.length > 1) {
      setMode("batch");
      applyPastedText(urls.join("\n"));
    } else {
      setMode("single");
      applyPastedText(urls[0]);
    }
    statusEl.textContent = urls.length > 1 ? `Dropped ${urls.length} URLs` : "URL dropped";
  });
})();

$("autoScroll").checked = localStorage.getItem("ytd_autoscroll") !== "0";
applyTheme(localStorage.getItem("ytd_theme") || "dark");
applyZoom(parseInt(localStorage.getItem("ytd_zoom") || "100", 10) || 100);
setMode("single");
updateMediaHints();
listenEvents();
refreshHealth().then(() => {
  // Auto-check GitHub releases once per day on open
  const day = new Date().toISOString().slice(0, 10);
  const last = localStorage.getItem("ytd_update_checked");
  if (last !== day) {
    localStorage.setItem("ytd_update_checked", day);
    checkAppUpdate({ interactive: false });
  }
});
refreshHistory();

// Prefill example playlist for local testing convenience (empty by default)
