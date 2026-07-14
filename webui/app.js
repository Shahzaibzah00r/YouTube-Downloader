const $ = (id) => document.getElementById(id);

const logEl = $("log");
const statusEl = $("status");
const barEl = $("bar");
const downloadBtn = $("downloadBtn");
const cancelBtn = $("cancelBtn");

let busy = false;
let mode = "single";
let es = null;

function appendLog(line, cls = "") {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
}

function setProgress(pct) {
  barEl.style.width = `${Math.max(0, Math.min(100, Number(pct) || 0))}%`;
}

function setBusy(on) {
  busy = on;
  downloadBtn.disabled = on;
  cancelBtn.disabled = !on;
  $("fixBtn").disabled = on;
  $("previewBtn").disabled = on;
}

function applyTheme(theme) {
  const t = theme === "light" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", t);
  localStorage.setItem("ytd_theme", t);
  $("themeBtn").textContent = t === "dark" ? "Light" : "Dark";
}

function currentUrls() {
  if (mode === "batch") {
    return $("batch").value
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
  }
  const one = $("url").value.trim();
  return one ? [one] : [];
}

function updateBatchCount() {
  const n = currentUrls().length;
  $("batchCount").textContent = `${n} URL${n === 1 ? "" : "s"}`;
}

function mediaMode() {
  const video = $("optVideo").checked;
  const audio = $("optAudio").checked;
  if (video && audio) return "both";
  if (audio) return "audio";
  // Default / neither → video
  if (!video && !audio) {
    $("optVideo").checked = true;
  }
  return "video";
}

function updateMediaHints() {
  const mode = mediaMode();
  const hints = {
    video: "Video selected — check both to save video + separate MP3",
    audio: "Audio only — saves an MP3",
    both: "Both selected — saves video and a separate MP3",
  };
  $("mediaHint").textContent = hints[mode] || hints.video;
  $("qualityBox").classList.toggle("is-disabled", mode === "audio");
  $("quality").disabled = mode === "audio";
}

function setMode(next) {
  mode = next;
  $("modeSingle").classList.toggle("active", mode === "single");
  $("modeBatch").classList.toggle("active", mode === "batch");
  $("singleBox").classList.toggle("hidden", mode !== "single");
  $("batchBox").classList.toggle("hidden", mode !== "batch");
  $("previewCard").classList.add("hidden");
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

function showPreview(data) {
  const card = $("previewCard");
  card.classList.remove("hidden");
  $("previewTitle").textContent = data.title || "Untitled";
  const bits = [];
  if (data.kind) bits.push(data.kind);
  if (data.filesize) bits.push(data.filesize);
  if (data.ext) bits.push(`.${data.ext}`);
  if (data.uploader) bits.push(data.uploader);
  $("previewSub").textContent = bits.join(" · ") || "Ready";
  const img = $("previewThumb");
  if (data.thumbnail) {
    img.src = data.thumbnail;
    img.classList.remove("hidden");
  } else {
    img.removeAttribute("src");
    img.classList.add("hidden");
  }
}

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    $("archPill").textContent = `${h.arch} · ${h.ready ? "ready" : "tools missing"}`;
    if (!$("outdir").value) $("outdir").value = h.default_dir || "";
    if (h.ready) {
      statusEl.textContent = "Ready — paste links and start downloading";
      appendLog(`Ready · yt-dlp=${h.yt_dlp}`, "ok");
      appendLog(`ffmpeg=${h.ffmpeg}`, "muted");
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
    if (msg.type === "progress") setProgress(msg.value);
    if (msg.type === "queue") {
      $("queueHint").textContent = msg.text || "";
    }
    if (msg.type === "done") {
      setBusy(false);
      setProgress(100);
      $("queueHint").textContent = "";
    }
    if (msg.type === "error") {
      setBusy(false);
      appendLog(msg.text, "err");
    }
  };
}

$("themeBtn").onclick = () => {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "dark" ? "light" : "dark");
};

$("modeSingle").onclick = () => setMode("single");
$("modeBatch").onclick = () => setMode("batch");
$("batch").addEventListener("input", updateBatchCount);

$("pasteBtn").onclick = async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (!text) return;
    if (mode === "batch") {
      const cur = $("batch").value.trim();
      $("batch").value = cur ? `${cur}\n${text.trim()}` : text.trim();
      updateBatchCount();
    } else {
      $("url").value = text.trim().split(/\r?\n/)[0];
    }
  } catch {
    statusEl.textContent = "Clipboard blocked — paste with ⌘V";
  }
};

$("previewBtn").onclick = async () => {
  const urls = currentUrls();
  if (!urls.length) {
    statusEl.textContent = "Enter a URL to preview";
    return;
  }
  statusEl.textContent = "Fetching preview…";
  try {
    const data = await api("/api/preview", {
      method: "POST",
      body: JSON.stringify({ url: urls[0] }),
    });
    showPreview(data);
    statusEl.textContent = "Preview ready";
  } catch (e) {
    $("previewCard").classList.add("hidden");
    statusEl.textContent = String(e.message || e);
    appendLog(String(e.message || e), "err");
  }
};

$("folderBtn").onclick = async () => {
  const h = await api("/api/health");
  $("outdir").value = h.default_dir;
};

$("openBtn").onclick = async () => {
  try {
    await api("/api/open-folder", {
      method: "POST",
      body: JSON.stringify({ path: $("outdir").value }),
    });
  } catch (e) {
    appendLog(String(e.message || e), "err");
  }
};

$("clearBtn").onclick = () => {
  logEl.textContent = "";
};

$("fixBtn").onclick = async () => {
  if (busy) return;
  setBusy(true);
  statusEl.textContent = "Installing yt-dlp and ffmpeg…";
  appendLog("Running brew install yt-dlp ffmpeg…", "muted");
  try {
    await api("/api/fix-tools", { method: "POST", body: "{}" });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    setBusy(false);
  }
};

$("cancelBtn").onclick = async () => {
  try {
    await api("/api/cancel", { method: "POST", body: "{}" });
    statusEl.textContent = "Cancelling…";
  } catch (e) {
    appendLog(String(e.message || e), "err");
  }
};

$("downloadBtn").onclick = async () => {
  if (busy) return;
  const urls = currentUrls();
  if (!urls.length) {
    statusEl.textContent = "Add at least one URL";
    return;
  }
  setBusy(true);
  setProgress(0);
  statusEl.textContent = urls.length > 1 ? `Queueing ${urls.length} downloads…` : "Downloading…";
  appendLog("");
  appendLog(`Starting ${urls.length} download(s)`, "ok");
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({
        urls,
        quality: $("quality").value,
        media: mediaMode(),
        outdir: $("outdir").value,
      }),
    });
  } catch (e) {
    appendLog(String(e.message || e), "err");
    statusEl.textContent = "Download failed to start";
    setBusy(false);
  }
};

$("url").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("downloadBtn").click();
});

$("optVideo").addEventListener("change", updateMediaHints);
$("optAudio").addEventListener("change", updateMediaHints);

applyTheme(localStorage.getItem("ytd_theme") || "dark");
setMode("single");
updateMediaHints();
listenEvents();
refreshHealth();
