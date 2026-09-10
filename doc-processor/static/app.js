let currentJobId = null;
let pollTimer = null;
let lastRows = [];
let showingErrorsOnly = false;

const $ = (id) => document.getElementById(id);

async function startProcessing() {
  const input_dir = $("inputDir").value.trim() || "INPUT";
  const output_dir = $("outputDir").value.trim() || "OUTPUT";

  $("processBtn").disabled = true;
  $("statusLine").textContent = "";
  $("progressFill").style.width = "0%";
  $("progressLabel").textContent = "Đang khởi động...";
  $("summaryCard").hidden = true;
  $("previewCard").hidden = true;

  try {
    const res = await fetch("/api/process", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ input_dir, output_dir }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    currentJobId = data.job_id;
    pollTimer = setInterval(pollJob, 800);
  } catch (e) {
    $("statusLine").textContent = "Lỗi: " + e.message;
    $("processBtn").disabled = false;
  }
}

async function pollJob() {
  if (!currentJobId) return;
  const res = await fetch(`/api/jobs/${currentJobId}`);
  if (!res.ok) return;
  const job = await res.json();

  const pct = job.total > 0 ? Math.round((job.processed / job.total) * 100) : (job.status === "done" ? 100 : 0);
  $("progressFill").style.width = pct + "%";
  $("progressLabel").textContent = `${pct}% — ${job.stage || job.status} (${job.processed}/${job.total})`;

  if (job.status === "error") {
    clearInterval(pollTimer);
    $("statusLine").textContent = "Lỗi: " + job.error;
    $("processBtn").disabled = false;
  } else if (job.status === "done") {
    clearInterval(pollTimer);
    $("processBtn").disabled = false;
    $("statusLine").textContent = "Hoàn tất.";
    renderSummary(job.summary);
    await loadPreview(false);
  }
}

function renderSummary(summary) {
  if (!summary) return;
  $("statTotal").textContent = summary.total_files;
  $("statComplete").textContent = summary.complete_sets;
  $("statIncomplete").textContent = summary.incomplete_sets;
  $("statValid").textContent = summary.valid_sets;
  $("statErrors").textContent = summary.error_files;
  $("statDuplicates").textContent = summary.duplicate_sets;
  $("summaryCard").hidden = false;
}

function statusBadge(status) {
  return `<span class="badge ${status}">${status}</span>`;
}

function renderPreview(rows) {
  lastRows = rows;
  const body = $("previewBody");
  body.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    const amount = row.amount != null ? Number(row.amount).toLocaleString("vi-VN") : "-";
    tr.innerHTML = `
      <td>${row.reference}</td>
      <td>${statusBadge(row.status)}</td>
      <td title="${row.issue}">${row.issue}</td>
      <td>${amount}</td>
      <td title="${row.folder || ""}">${row.folder || "-"}</td>
    `;
    body.appendChild(tr);
  }
  $("previewCard").hidden = false;
}

async function loadPreview(errorsOnly) {
  showingErrorsOnly = errorsOnly;
  const res = await fetch(`/api/jobs/${currentJobId}/preview?errors_only=${errorsOnly}`);
  if (!res.ok) return;
  renderPreview(await res.json());
  $("viewAllBtn").hidden = !errorsOnly;
}

async function openFolder() {
  const res = await fetch(`/api/jobs/${currentJobId}/open-folder`, { method: "POST" });
  const data = await res.json();
  $("pathHint").textContent = data.opened
    ? `Đã mở: ${data.path}`
    : `Không thể tự mở trên môi trường này. Đường dẫn: ${data.path}`;
}

function exportFile(kind) {
  window.location.href = `/api/jobs/${currentJobId}/export/${kind}`;
}

$("processBtn").addEventListener("click", startProcessing);
$("openFolderBtn").addEventListener("click", openFolder);
$("exportMisaBtn").addEventListener("click", () => exportFile("misa"));
$("exportReconBtn").addEventListener("click", () => exportFile("reconciliation"));
$("viewErrorsBtn").addEventListener("click", () => loadPreview(true));
$("viewAllBtn").addEventListener("click", () => loadPreview(false));
