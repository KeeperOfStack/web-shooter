// WEB-SHOOTER frontend — talks to the docscrape FastAPI on the same origin.

const $ = (id) => document.getElementById(id);

const form     = $("scrape-form");
const goBtn    = $("go");
const statusEl = $("status-card");
const sJob     = $("s-job");
const sUrl     = $("s-url");
const sMode    = $("s-mode");
const sPages   = $("s-pages");
const sCur     = $("s-cur");
const bar      = $("bar");
const result   = $("result");
const ctxList  = $("context-list");
const queueList = $("queue-list");

let poller = null;
let queuePoller = null;

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024*1024) return (n/1024).toFixed(1) + " KB";
  return (n/1024/1024).toFixed(2) + " MB";
}

function fmtAge(ts) {
  if (!ts) return "";
  const s = Math.round(Date.now()/1000 - ts);
  if (s < 60) return s + "s ago";
  if (s < 3600) return Math.round(s/60) + "m ago";
  return Math.round(s/3600) + "h ago";
}

async function refreshQueue() {
  try {
    const r = await fetch("/jobs");
    const jobs = await r.json();
    if (!jobs.length) {
      queueList.innerHTML = '<span class="queue-empty">no jobs yet — fire a web-shot above!</span>';
      return;
    }
    queueList.innerHTML = jobs.map(j => {
      const statusCls = j.status === "complete" ? "complete" : j.status === "error" ? "error" : "running";
      const statusLabel = j.status.toUpperCase();
      const maxP = j.max || 200;
      const pct = j.status === "complete" ? 100 : Math.min(99, Math.round((j.pages_done||0)/maxP*100));
      const age = fmtAge(j.started_at);
      const art = j.artifact || {};

      let info = `${j.mode} · ${j.pages_done||0} pages`;
      if (j.status === "running" && j.current_url) info += ` · <em style="font-weight:400">${j.current_url.slice(0,60)}</em>`;
      if (j.status === "complete") info += ` · ${fmtBytes(art.size)} · ${age}`;
      if (j.status === "error") info += ` · ${j.error || "unknown error"}`;

      const bar = j.status === "running"
        ? `<div class="queue-bar-wrap"><div class="queue-bar" style="width:${pct}%"></div></div>`
        : "";

      let actions = "";
      if (j.status === "complete") {
        actions += `<a href="/jobs/${j.job_id}/download" title="Download">⬇ DL</a>`;
      }
      actions += `<button data-jid="${j.job_id}" class="del-job" title="Remove">✕</button>`;

      return `<div class="queue-row">
        <span class="qbadge ${statusCls}">${statusLabel}</span>
        <div class="qmeta">
          <div class="qurl">${j.url}</div>
          <div class="qinfo">${info}${bar}</div>
        </div>
        <div class="qactions">${actions}</div>
      </div>`;
    }).join("");

    queueList.querySelectorAll("button.del-job").forEach(btn => {
      btn.addEventListener("click", async () => {
        await fetch("/jobs/" + btn.dataset.jid, { method: "DELETE" });
        refreshQueue();
        refreshContext();
      });
    });
  } catch (err) {
    queueList.innerHTML = '<span class="queue-empty">could not load queue.</span>';
  }
}

function selectedChoice() {
  const v = document.querySelector('input[name="choice"]:checked').value;
  const [mode, sink] = v.split("-");
  return { mode, sink };
}

async function refreshContext() {
  try {
    const r = await fetch("/context");
    const data = await r.json();
    if (!data.entries || data.entries.length === 0) {
      ctxList.innerHTML = '<em>nothing in <code>'+data.context_dir+'</code> yet.</em>';
      return;
    }
    ctxList.innerHTML = data.entries.map(e => {
      const badge = e.kind === "split"
        ? '<span class="badge">SPLIT</span>'
        : '<span class="badge single">SINGLE</span>';
      const meta = e.kind === "split"
        ? `${e.file_count} files · ${fmtBytes(e.size)}`
        : `${fmtBytes(e.size)}`;
      return `<div class="ctx-row">
        ${badge}
        <span class="name">${e.name}</span>
        <span class="size">${meta}</span>
        <button data-name="${encodeURIComponent(e.name)}">remove</button>
      </div>`;
    }).join("");
    ctxList.querySelectorAll("button[data-name]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const name = decodeURIComponent(btn.dataset.name);
        if (!confirm(`Remove "${name}" from the context library?`)) return;
        await fetch("/context/" + encodeURIComponent(name), {method:"DELETE"});
        refreshContext();
      });
    });
  } catch (err) {
    ctxList.innerHTML = '<em>could not load context list.</em>';
  }
}

function showResult(kind, html) {
  result.className = "result show " + kind;
  result.innerHTML = html;
}

async function pollJob(jobId, sink) {
  try {
    const r = await fetch("/jobs/" + jobId);
    if (!r.ok) throw new Error("status " + r.status);
    const j = await r.json();
    sPages.textContent = j.pages_done ?? 0;
    sCur.textContent   = j.current_url || "…";
    const maxP = parseInt($("max").value, 10) || 200;
    const pct = Math.min(100, Math.round((j.pages_done || 0) / maxP * 100));
    bar.style.width = pct + "%";

    if (j.status === "complete") {
      clearInterval(poller); poller = null;
      goBtn.disabled = false;
      bar.style.width = "100%";
      refreshQueue();
      const art = j.artifact || {};
      const lines = [];
      lines.push(`<strong>✓ DONE.</strong> ${j.pages_done} pages scraped.`);
      if (art.kind === "folder") {
        lines.push(`Built <code>${art.file_count}</code> markdown files.`);
      }
      if (sink === "context" && art.context_path) {
        lines.push(`<div style="margin-top:.5rem">Delivered to context library:<br><code>${art.context_path}</code></div>`);
      } else if (sink === "context" && art.context_skipped) {
        lines.push(`<div style="margin-top:.5rem">⚠ context entry already existed and overwrite was off:<br><code>${art.context_skipped}</code></div>`);
      }
      if (sink === "download") {
        lines.push(`<a class="dlbtn" href="/jobs/${jobId}/download">⬇ DOWNLOAD ${art.name || "result"}</a>`);
      }
      showResult("ok", lines.join(""));
      refreshContext();
    } else if (j.status === "error") {
      clearInterval(poller); poller = null;
      goBtn.disabled = false;
      refreshQueue();
      showResult("err", `<strong>✗ FAILED.</strong> ${j.error || "unknown error"}`);
    }
  } catch (err) {
    console.warn("poll error", err);
  }
}

form.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  if (poller) { clearInterval(poller); poller = null; }
  result.className = "result"; result.innerHTML = "";

  const { mode, sink } = selectedChoice();
  const body = {
    url:                 $("url").value.trim(),
    max:                 parseInt($("max").value, 10) || 200,
    delay:               parseFloat($("delay").value) || 0.2,
    mode:                mode,
    deliver_to_context:  sink === "context",
    overwrite:           $("overwrite").value === "true",
    embed_images:        $("embed-images").value === "true",
  };

  goBtn.disabled = true;
  statusEl.classList.remove("hidden");
  sUrl.textContent  = body.url;
  sMode.textContent = `${mode.toUpperCase()} → ${sink.toUpperCase()}`;
  sPages.textContent = "0";
  sCur.textContent  = "…";
  bar.style.width = "0%";

  let resp;
  try {
    resp = await fetch("/scrape", {
      method: "POST",
      headers: {"content-type": "application/json"},
      body: JSON.stringify(body),
    });
  } catch (err) {
    goBtn.disabled = false;
    showResult("err", `<strong>✗ network error:</strong> ${err.message}`);
    return;
  }
  if (!resp.ok) {
    goBtn.disabled = false;
    const txt = await resp.text();
    showResult("err", `<strong>✗ ${resp.status}:</strong> <pre>${txt}</pre>`);
    return;
  }
  const j = await resp.json();
  sJob.textContent = j.job_id;
  poller = setInterval(() => pollJob(j.job_id, sink), 1500);
  pollJob(j.job_id, sink);
});

refreshContext();
refreshQueue();
queuePoller = setInterval(refreshQueue, 3000);
