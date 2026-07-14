const $ = (id) => document.getElementById(id);

const logEl = $("log");
const statusEl = $("status");
const barEl = $("bar");
const downloadBtn = $("downloadBtn");
const cancelBtn = $("cancelBtn");

let busy = false;
let es = null;

function appendLog(line, cls = "") {
  const span = document.createElement("span");
  if (cls) span.className = cls;
  span.textContent = line + "\n";
  logEl.appendChild(span);
  logEl.scrollTop = logEl.scrollHeight;
}

function setProgress(pct) {
  const n = Math.max(0, Math.min(100, Number(pct) || 0));
  barEl.style.width = `${n}%`;
}

function setBusy(on) {
  busy = on;
  downloadBtn.disabled = on;
  cancelBtn.disabled = !on;
  $("fixBtn").disabled = on;
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

async function refreshHealth() {
  try {
    const h = await api("/api/health");
    $("archPill").textContent = `${h.arch} · ${h.ready ? "ready" : "tools missing"}`;
    $("outdir").value = h.default_dir || $("outdir").value;
    if (h.ready) {
      statusEl.textContent = "Ready — paste a link and click Download";
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
    if (msg.type === "done") {
      setBusy(false);
      setProgress(100);
    }
    if (msg.type === "error") {
      setBusy(false);
      appendLog(msg.text, "err");
    }
  };
}

$("pasteBtn").onclick = async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (text) $("url").value = text.trim();
  } catch {
    statusEl.textContent = "Clipboard blocked — paste with ⌘V into the URL field";
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
  const url = $("url").value.trim();
  if (!url) {
    statusEl.textContent = "Paste a YouTube URL first";
    return;
  }
  setBusy(true);
  setProgress(0);
  statusEl.textContent = "Downloading…";
  appendLog("");
  appendLog(`Downloading: ${url}`, "ok");
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({
        url,
        quality: $("quality").value,
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

listenEvents();
refreshHealth();
