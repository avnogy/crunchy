const expandedJobs = new Set();
const requestedJobId = new URLSearchParams(window.location.search).get("job");
const pollIntervalMs = Math.max(500, Number(window.jobsPollIntervalMs) || 3000);
const jobsContainer = document.getElementById("jobs-list");
const pollController = window.ui.startPolling(loadJobs, pollIntervalMs);

const JOB_STATE_CLASSES = {
  completed: "ui-status-success",
  failed: "ui-status-danger",
  running: "ui-status-info",
  queued: "ui-status-warning",
  cancelled: "ui-status-muted",
};

if (requestedJobId) {
  expandedJobs.add(requestedJobId);
}

function formatDuration(totalSeconds) {
  const safeSeconds = Math.max(0, Number(totalSeconds) || 0);
  const hours = Math.floor(safeSeconds / 3600);
  const mins = Math.floor((safeSeconds % 3600) / 60);
  const secs = Math.round(safeSeconds % 60);

  if (hours > 0) {
    return `${hours.toString().padStart(2, "0")}:${mins
      .toString()
      .padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }

  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

function getCurrentSeconds(job) {
  return typeof job.progress?.current_seconds === "number"
    ? job.progress.current_seconds
    : NaN;
}

function getEta(job) {
  if (!job.progress?.duration || !job.speed) {
    return "-";
  }

  const currentSecs = getCurrentSeconds(job);
  const speed = Number.parseFloat(job.speed);
  if (!Number.isFinite(currentSecs) || currentSecs <= 0 || speed <= 0) {
    return "-";
  }

  const etaMinutes = Math.round(
    (job.progress.duration - currentSecs) / speed / 60,
  );
  return etaMinutes > 0 ? `${etaMinutes}m` : "-";
}

function formatCurrentTime(job) {
  const totalSeconds = getCurrentSeconds(job);
  return Number.isFinite(totalSeconds) && totalSeconds >= 0
    ? formatDuration(totalSeconds)
    : "-";
}

function getStateClasses(state) {
  return JOB_STATE_CLASSES[state] || JOB_STATE_CLASSES.cancelled;
}

function renderIcon(name, extraClass = "") {
  return `<i data-lucide="${name}" class="h-5 w-5 ${extraClass}" aria-hidden="true"></i>`;
}

function refreshIcons() {
  window.lucide?.createIcons?.();
}

function renderActions(job) {
  const canDownload = job.state === "completed" && job.download_available;
  const jobId = encodeURIComponent(job.id);
  const downloadButton = canDownload
    ? `<a href="/api/jobs/${jobId}/download" class="ui-button-primary inline-flex h-10 w-10 items-center justify-center rounded-lg transition" title="Download" aria-label="Download">${renderIcon("download")}</a>`
    : `<button type="button" disabled class="inline-flex h-10 w-10 cursor-not-allowed items-center justify-center rounded-lg bg-slate-200 text-slate-400" title="Download unavailable" aria-label="Download unavailable">${renderIcon("download")}</button>`;
  const renderLogLink = () =>
    `<a href="/api/jobs/${jobId}/log" target="_blank" rel="noopener" class="ui-button-secondary inline-flex h-10 w-10 items-center justify-center rounded-lg border transition" title="View log" aria-label="View log">${renderIcon("file-text")}</a>`;
  const cancelButton = `<button type="button" data-cancel-job="${window.ui.escapeHtml(job.id)}" class="ui-button-danger ml-auto inline-flex h-10 w-10 items-center justify-center rounded-lg border transition" title="Cancel job" aria-label="Cancel job">${renderIcon("x")}</button>`;
  const deleteButton = `<button type="button" data-delete-job="${window.ui.escapeHtml(job.id)}" class="ui-button-danger ml-auto inline-flex h-10 w-10 items-center justify-center rounded-lg border transition" title="Delete job" aria-label="Delete job">${renderIcon("trash-2")}</button>`;

  if (job.state === "completed") {
    return `${downloadButton}${job.log_path ? renderLogLink() : ""}${deleteButton}`;
  }
  if (job.state === "running") {
    return `${downloadButton}${job.log_path ? renderLogLink() : ""}${cancelButton}`;
  }
  if (job.state === "queued") {
    return `${downloadButton}${job.log_path ? renderLogLink() : ""}${cancelButton}`;
  }
  if (job.log_path) {
    return `${downloadButton}${renderLogLink()}${deleteButton}`;
  }

  return `${downloadButton}${deleteButton}`;
}

function renderMetaRow(label, value, extraClass = "") {
  return `
    <div class="${extraClass}">
      <dt class="text-sm text-gray-500">${label}</dt>
      <dd class="break-all text-gray-700">${value}</dd>
    </div>
  `;
}

function renderJobCard(job) {
  const expanded = expandedJobs.has(job.id);
  const safeJobId = window.ui.escapeHtml(job.id);
  const safeItemName = window.ui.escapeHtml(job.item_name);
  const itemPageId = encodeURIComponent(job.item_id);
  const safePresetName = window.ui.escapeHtml(
    job.preset?.name || job.preset || "",
  );
  const safeErrorMessage = window.ui.escapeHtml(job.error_message || "");
  const safeState = window.ui.escapeHtml(job.state || "");
  const showProgress = job.state === "running" || job.state === "queued";
  const progressSummary = showProgress
    ? `
      <span class="text-sm text-gray-500">${window.ui.escapeHtml(formatCurrentTime(job))} / ${window.ui.escapeHtml(job.progress?.duration ? formatDuration(job.progress.duration) : "-")}</span>
      <span class="text-sm text-slate-600">ETA ${window.ui.escapeHtml(getEta(job))}</span>
    `
    : job.error_message
      ? `<span class="max-w-full truncate text-sm text-red-600">${safeErrorMessage}</span>`
      : "";

  const details = [
    renderMetaRow("ID", `<span class="font-mono text-sm">${safeJobId}</span>`),
    renderMetaRow("State", safeState),
    renderMetaRow("Created", window.ui.escapeHtml(job.created_at || "-")),
    renderMetaRow("Started", window.ui.escapeHtml(job.started_at || "-")),
    renderMetaRow("Finished", window.ui.escapeHtml(job.finished_at || "-")),
  ];

  if (showProgress) {
    details.push(
      renderMetaRow("Speed", window.ui.escapeHtml(job.speed || "-")),
    );
    details.push(
      renderMetaRow(
        "Duration",
        job.progress?.duration
          ? window.ui.escapeHtml(formatDuration(job.progress.duration))
          : "-",
      ),
    );
  }
  if (job.output_path) {
    details.push(
      renderMetaRow(
        "Output",
        window.ui.escapeHtml(job.output_path),
        "md:col-span-2",
      ),
    );
  }
  if (job.error_message) {
    details.push(renderMetaRow("Error", safeErrorMessage, "md:col-span-2"));
  }
  return `
    <article class="overflow-hidden rounded-xl border border-slate-200 bg-slate-50">
      <div class="bg-white px-5 py-4">
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-3">
              <a href="/items/${itemPageId}" class="font-semibold text-slate-900 transition hover:text-slate-700 hover:underline">${safeItemName}</a>
              <span class="rounded-full px-3 py-1 text-sm font-medium ${getStateClasses(job.state)}">${safeState}</span>
              <span class="text-sm text-slate-500">${safePresetName}</span>
              ${progressSummary}
            </div>
          </div>
          <div class="flex min-w-[120px] flex-wrap items-center gap-3">
            ${renderActions(job)}
          </div>
        </div>
      </div>
      <button
        type="button"
        data-toggle-job="${safeJobId}"
        class="flex h-7 w-full items-center justify-center border-t border-slate-200 bg-slate-100 text-slate-500 transition hover:bg-slate-200 hover:text-slate-700"
        aria-expanded="${expanded ? "true" : "false"}"
        title="${expanded ? "Collapse details" : "Expand details"}"
        aria-label="${expanded ? "Collapse details" : "Expand details"}"
      >
        <span class="transform ${expanded ? "rotate-180" : ""}">${renderIcon("chevron-down")}</span>
      </button>
      <div class="${expanded ? "block" : "hidden"} border-t border-slate-200 bg-slate-50 px-5 pb-5">
        <dl class="grid gap-4 pt-5 md:grid-cols-2">
          ${details.join("")}
        </dl>
      </div>
    </article>
  `;
}

async function cancelJob(jobId) {
  if (!window.confirm("Cancel this job?")) {
    return;
  }

  try {
    await window.ui.request(`/api/jobs/${jobId}/cancel`, { method: "POST" });
    await loadJobs();
  } catch (error) {
    toast.error("Failed to cancel");
  }
}

async function deleteJob(jobId) {
  if (!window.confirm("Delete this job and all related files?")) {
    return;
  }

  try {
    await window.ui.request(`/api/jobs/${jobId}`, { method: "DELETE" });
    expandedJobs.delete(jobId);
    await loadJobs();
  } catch (error) {
    toast.error(error?.message || "Failed to delete");
  }
}

async function loadJobs() {
  if (!jobsContainer) {
    return;
  }

  try {
    const data = await window.ui.request("/api/jobs");
    const jobs = data.jobs || [];

    if (requestedJobId && jobs.some((job) => job.id === requestedJobId)) {
      expandedJobs.add(requestedJobId);
    }

    if (jobs.length === 0) {
      jobsContainer.innerHTML = window.ui.renderEmptyState("No jobs yet.");
      return;
    }

    jobsContainer.innerHTML = `<div class="space-y-4">${jobs.map(renderJobCard).join("")}</div>`;
    refreshIcons();
  } catch (error) {
    toast.error("Failed to load");
  }
}

document.addEventListener("click", (event) => {
  const toggleButton = event.target.closest("[data-toggle-job]");
  if (toggleButton) {
    const jobId = toggleButton.dataset.toggleJob;
    if (expandedJobs.has(jobId)) {
      expandedJobs.delete(jobId);
    } else {
      expandedJobs.add(jobId);
    }
    loadJobs();
    return;
  }

  const cancelButton = event.target.closest("[data-cancel-job]");
  if (cancelButton) {
    cancelJob(cancelButton.dataset.cancelJob);
    return;
  }

  const deleteButton = event.target.closest("[data-delete-job]");
  if (deleteButton) {
    deleteJob(deleteButton.dataset.deleteJob);
  }
});

document.getElementById("poll-toggle")?.addEventListener("change", (event) => {
  if (event.target.checked) {
    pollController.start();
    return;
  }

  pollController.stop();
});

pollController.start();
