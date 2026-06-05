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

let poller = null;

function fmtBytes(n) {
  if (n == null) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024*1024) return (n/1024).toFixed(1) + " KB";
  return (n/1024/1024).toFixed(2) + " MB";
}

function selectedChoice() {
  const v = document.querySelector('input[name="choice"]:checked').value;
  // value format: "<mode>-<sink>"
  const [mode, sink] = v.split("-");
  return { mode, sink };  // sink: "download" or "context"
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
      showResult("err", `<strong>✗ FAILED.</strong> ${j.error || "unknown error"}`);
    }
  } catch (err) {
    // transient — keep polling
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
