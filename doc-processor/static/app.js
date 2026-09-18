let currentJobId = null;
let pollTimer = null;
let lastRows = [];
let showingErrorsOnly = false;
let selectedFiles = [];

const $ = (id) => document.getElementById(id);
const ACCEPTED_EXTENSIONS = [".pdf", ".zip", ".xlsx", ".xls"];

function formatBytes(n) {
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(1) + " MB";
}

function hasAcceptedExtension(name) {
  const lower = name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext));
}

function renderFileList() {
  const list = $("fileList");
  list.innerHTML = "";
  for (const f of selectedFiles) {
    const row = document.createElement("div");
    row.className = "file-row";
    row.innerHTML = `<span>${f.name}${hasAcceptedExtension(f.name) ? "" : " ⚠ (bỏ qua)"}</span><span class="size">${formatBytes(f.size)}</span>`;
    list.appendChild(row);
  }
  $("uploadBtn").disabled = selectedFiles.length === 0;
}

function addFiles(fileListLike) {
  for (const f of fileListLike) {
    if (!selectedFiles.some((existing) => existing.name === f.name && existing.size === f.size)) {
      selectedFiles.push(f);
    }
  }
  renderFileList();
}

async function uploadSelectedFiles() {
  if (selectedFiles.length === 0) return;
  $("uploadBtn").disabled = true;
  $("uploadStatus").textContent = "Đang tải lên...";

  const form = new FormData();
  for (const f of selectedFiles) form.append("files", f);

  try {
    const res = await fetch("/api/upload", { method: "POST", body: form });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    $("inputDir").value = data.input_dir;
    let msg = `Đã tải lên ${data.files_received.length} file.`;
    if (data.skipped.length) msg += ` Bỏ qua ${data.skipped.length} file không hỗ trợ: ${data.skipped.join(", ")}`;
    $("uploadStatus").textContent = msg;
  } catch (e) {
    $("uploadStatus").textContent = "Lỗi tải file lên: " + e.message;
  } finally {
    $("uploadBtn").disabled = selectedFiles.length === 0;
  }
}

function setupUploadUi() {
  const dropZone = $("dropZone");
  const fileInput = $("fileInput");

  $("browseBtn").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => addFiles(fileInput.files));

  ["dragenter", "dragover"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.add("dragover");
    })
  );
  ["dragleave", "drop"].forEach((evt) =>
    dropZone.addEventListener(evt, (e) => {
      e.preventDefault();
      dropZone.classList.remove("dragover");
    })
  );
  dropZone.addEventListener("drop", (e) => {
    if (e.dataTransfer && e.dataTransfer.files) addFiles(e.dataTransfer.files);
  });

  $("uploadBtn").addEventListener("click", uploadSelectedFiles);
}

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
$("exportExtractedBtn").addEventListener("click", () => exportFile("extracted"));
$("exportReconBtn").addEventListener("click", () => exportFile("reconciliation"));
$("viewErrorsBtn").addEventListener("click", () => loadPreview(true));
$("viewAllBtn").addEventListener("click", () => loadPreview(false));

setupUploadUi();
